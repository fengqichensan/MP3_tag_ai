"use strict";
/*
 * ID3Lite —— 纯 JS 的 MP3 ID3 标签 读取/写入，零依赖，可离线运行。
 *
 * 用途：「直改本地文件」模式：浏览器通过 File System Access API 直接读写
 * 用户本地磁盘上的 MP3，文件内容不经过服务器。
 *
 * 读取：支持 ID3v2.2 / v2.3 / v2.4（含 unsynchronisation、扩展头、
 *       数据长度指示器），以及无 v2 标签时的 ID3v1 / v1.1 回退。
 * 写入：整体重建 ID3v2.3 标签（UTF-16LE w/ BOM 编码，兼容性最好），
 *       空字符串字段不写入对应帧（即删除该字段），音频数据原样保留。
 *
 * API:
 *   ID3Lite.read(arrayBuffer)            -> {track,title,artist,album}（无标签返回空串）
 *                                           数据损坏时 throw Error
 *   ID3Lite.write(arrayBuffer, tags)     -> ArrayBuffer（新文件字节）
 */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(); // Node（用于对拍测试）
  } else {
    root.ID3Lite = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {

  const FIELDS = ["track", "title", "artist", "album"];

  // ------------------------------------------------------------ 基础工具

  function syncSafeToInt(b0, b1, b2, b3) {
    return ((b0 & 0x7f) << 21) | ((b1 & 0x7f) << 14) | ((b2 & 0x7f) << 7) | (b3 & 0x7f);
  }
  function u32be(view, off) {
    return view.getUint32(off, false);
  }

  // FF 00 -> FF 去除逆同步
  function deUnsync(bytes) {
    const out = new Uint8Array(bytes.length);
    let j = 0;
    for (let i = 0; i < bytes.length; i++) {
      out[j++] = bytes[i];
      if (bytes[i] === 0xff && i + 1 < bytes.length && bytes[i + 1] === 0x00) i++;
    }
    return out.subarray(0, j);
  }

  // 解码文本帧正文（不含 encoding 字节）。返回去掉终止符后的字符串数组。
  function decodeTextPayload(bytes, enc) {
    let text = "";
    try {
      if (enc === 1 || enc === 2) {
        // UTF-16：按 BOM 决定端序；v2.4 允许无 BOM 时默认 BE（规范为带 BOM 的 UTF-16LE/BE）
        let start = 0;
        let le = false;
        if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) { le = true; start = 2; }
        else if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) { le = false; start = 2; }
        else if (enc === 1) le = true; // 无 BOM 的 enc=1 少见，宽容处理
        text = new TextDecoder(le ? "utf-16le" : "utf-16be")
          .decode(bytes.subarray(start));
      } else if (enc === 3) {
        text = new TextDecoder("utf-8").decode(bytes);
      } else {
        text = new TextDecoder("windows-1252").decode(bytes);
      }
    } catch (e) {
      return [];
    }
    // 去掉结尾的 \u0000（以及 CRLF 规范化由调用方决定）
    const parts = text.split("\u0000");
    while (parts.length && parts[parts.length - 1] === "") parts.pop();
    return parts.map((s) => s.replace(/\r?\n/g, " ").trim()).filter((s) => s !== "");
  }

  // ------------------------------------------------------------ v2 解析

  const V22_MAP = { TT2: "TIT2", TP1: "TPE1", TAL: "TALB", TRK: "TRCK" };

  function parseId3v2(u8) {
    const major = u8[3];
    const flags = u8[4];
    const tagSize = syncSafeToInt(u8[6], u8[7], u8[8], u8[9]); // 不含 10 字节头

    let body = u8.subarray(10, Math.min(10 + tagSize, u8.length));
    if (flags & 0x80 && major !== 4) body = deUnsync(body); // 整体逆同步（v2.4 为逐帧）

    const result = {};
    const put = (fid, value) => {
      if (!value) return;
      if (fid === "TRCK") result.track = result.track || value;
      else if (fid === "TIT2") result.title = result.title || value;
      else if (fid === "TPE1") result.artist = result.artist || value;
      else if (fid === "TALB") result.album = result.album || value;
    };

    let pos = 0;
    // 扩展头跳过（v2.3 的长度值不含自身 4 字节；v2.4 含）
    if (flags & 0x40) {
      if (major === 3) {
        if (pos + 4 > body.length) return result;
        pos += u32beF(body, pos) + 4;
      } else if (major === 4) {
        if (pos + 4 > body.length) return result;
        pos += syncSafeIntB(body, pos);
      }
    }

    const idLen = major === 2 ? 3 : 4;
    const sizeLen = major === 2 ? 3 : 4;

    while (pos + idLen + sizeLen <= body.length) {
      // padding：帧头全是 0 即结束
      let zero = true;
      for (let k = 0; k < idLen + sizeLen; k++) {
        if (body[pos + k] !== 0) { zero = false; break; }
      }
      if (zero) break;

      let fid = latin1View(body, pos, idLen);
      if (major === 2) fid = V22_MAP[fid] || fid;

      let fsize;
      if (major === 2) fsize = (body[pos + 3] << 16) | (body[pos + 4] << 8) | body[pos + 5];
      else if (major === 3) fsize = u32beF(body, pos + 4);
      else fsize = syncSafeIntB(body, pos + 4);

      const hdrLen = idLen + sizeLen + (major === 2 ? 0 : 2); // v2.3/4 还有 2 字节标志
      if (fsize <= 0 || pos + hdrLen + fsize > body.length) break;

      let content = body.subarray(pos + hdrLen, pos + hdrLen + fsize);

      let skip = false;
      if (major === 3) {
        const ff = body[pos + 8], sf = body[pos + 9];
        if (ff & 0x80 || ff & 0x40) skip = true;          // 压缩 / 加密
        else if (ff & 0x20) content = content.subarray(1); // 分组标识
      } else if (major === 4) {
        const ff = body[pos + 8], fmt = body[pos + 9];
        if (fmt & 0x08 || fmt & 0x04) skip = true;         // 压缩 / 加密
        else {
          if (fmt & 0x40) content = content.subarray(1);   // 分组标识
          if (fmt & 0x01) content = content.subarray(4);   // 数据长度指示器
          if (fmt & 0x02) content = deUnsync(content);     // 帧级逆同步
        }
      }

      pos += hdrLen + fsize;

      if (skip || !fid.startsWith("T") || content.length === 0) continue;
      const enc = content[0];
      const values = decodeTextPayload(content.subarray(1), enc);
      if (values.length) put(fid, values.join("/"));
    }
    return result;
  }
  function u32beF(b, o) { return (b[o] << 24 | b[o + 1] << 16 | b[o + 2] << 8 | b[o + 3]) >>> 0; }
  function syncSafeIntB(b, o) { return syncSafeToInt(b[o], b[o + 1], b[o + 2], b[o + 3]); }
  function latin1View(b, o, l) {
    let s = "";
    for (let i = 0; i < l; i++) s += String.fromCharCode(b[o + i]);
    return s;
  }

  // ------------------------------------------------------------ v1 回退

  function parseId3v1(u8) {
    if (u8.length < 128) return null;
    const tail = u8.subarray(u8.length - 128);
    if (latin1View(tail, 0, 3) !== "TAG") return null;
    const dec = (off, len) => {
      const raw = tail.subarray(off, off + len);
      for (const enc of ["utf-8", "gbk"]) {
        try {
          // 老编码器可能用 NUL 或空格填充，都容忍
          const s = new TextDecoder(enc, { fatal: true })
            .decode(raw).replace(/[\u0000 ]+$/, "").trim();
          if (s) return s;
        } catch (e) { /* 试下一种编码 */ }
      }
      return "";
    };
    let track = "";
    if (tail[126] === 0 && tail[127] > 0) track = String(tail[127]); // v1.1
    return {
      track,
      title: dec(3, 30),
      artist: dec(33, 30),
      album: dec(63, 30),
    };
  }

  // ------------------------------------------------------------ 对外读取

  function read(arrayBuffer) {
    const empty = { track: "", title: "", artist: "", album: "" };
    const u8 = arrayBuffer instanceof Uint8Array ? arrayBuffer : new Uint8Array(arrayBuffer);
    if (u8.length < 10) return empty;
    if (!(u8[0] === 0x49 && u8[1] === 0x44 && u8[2] === 0x33)) {
      const v1 = parseId3v1(u8);
      if (!v1) return empty;
      return { track: v1.track, title: v1.title, artist: v1.artist, album: v1.album };
    }
    const parsed = parseId3v2(u8);
    const out = {};
    for (const f of FIELDS) out[f] = parsed[f] || "";
    return out;
  }

  // ------------------------------------------------------------ 写入

  function utf16Bom(str) {
    // FF FE + UTF-16LE + 双零终止符
    const chars = [];
    for (const ch of str) chars.push(ch.codePointAt(0));
    const out = new Uint8Array(2 + chars.reduce((n, c) => n + (c > 0xffff ? 4 : 2), 0) + 2);
    out[0] = 0xff; out[1] = 0xfe;
    let p = 2;
    for (const c of chars) {
      if (c > 0xffff) {
        c -= 0x10000;
        const hi = 0xd800 + (c >> 10), lo = 0xdc00 + (c & 0x3ff);
        out[p++] = hi & 0xff; out[p++] = hi >> 8;
        out[p++] = lo & 0xff; out[p++] = lo >> 8;
      } else {
        out[p++] = c & 0xff; out[p++] = c >> 8;
      }
    }
    out[p++] = 0; out[p++] = 0; // 终止符
    return out;
  }

  function frame(id, str) {
    const payload = utf16Bom(str);
    const out = new Uint8Array(10 + 1 + payload.length); // 1 字节 encoding=01 (UTF-16 w/BOM)
    for (let i = 0; i < 4; i++) out[i] = id.charCodeAt(i);
    const fsize = payload.length + 1;
    out[4] = (fsize >>> 24) & 0xff;
    out[5] = (fsize >>> 16) & 0xff;
    out[6] = (fsize >>> 8) & 0xff;
    out[7] = fsize & 0xff;
    // flags 全 0
    out[10] = 1; // encoding: UTF-16 with BOM
    out.set(payload, 11);
    return out;
  }

  function intToSyncSafe(n) {
    return [(n >> 21) & 0x7f, (n >> 14) & 0x7f, (n >> 7) & 0x7f, n & 0x7f];
  }

  // 计算已有 v2 标签总长（含头与可能的 footer），返回需跳过的字节数
  function existingTagLength(u8) {
    if (u8.length < 10 || !(u8[0] === 0x49 && u8[1] === 0x44 && u8[2] === 0x33)) return 0;
    const size = syncSafeToInt(u8[6], u8[7], u8[8], u8[9]);
    let total = 10 + size;
    if (u8[5] & 0x10 && u8.length >= total + 10 &&
        u8[total] === 0x33 && u8[total + 1] === 0x44 && u8[total + 2] === 0x49) {
      total += 10; // footer "3DI"
    }
    return Math.min(total, u8.length);
  }

  /**
   * 用新标签重建整个文件字节：
   *  - tags 中非空字段写成对应帧，空字段不写（等效删除）
   *  - 音频数据 = 原 buffer 去掉旧 ID3v2 头之后的全部内容（ID3v1 保留在尾部）
   */
  function write(arrayBuffer, tags) {
    const u8 = arrayBuffer instanceof Uint8Array ? arrayBuffer : new Uint8Array(arrayBuffer);
    const audioStart = existingTagLength(u8);

    const frames = [];
    const t = tags || {};
    const val = (k) => String(t[k] ?? "").trim();
    if (val("track")) frames.push(frame("TRCK", val("track")));
    if (val("title")) frames.push(frame("TIT2", val("title")));
    if (val("artist")) frames.push(frame("TPE1", val("artist")));
    if (val("album")) frames.push(frame("TALB", val("album")));

    const padTo = 512;
    const framesLen = frames.reduce((n, f) => n + f.length, 0);
    const padding = framesLen % padTo === 0 ? 0 : padTo - (framesLen % padTo);
    const tagLen = 10 + framesLen + padding;

    const out = new Uint8Array(tagLen + Math.max(0, u8.length - audioStart));
    out[0] = 0x49; out[1] = 0x44; out[2] = 0x33; // "ID3"
    out[3] = 3; out[4] = 0;                       // v2.3
    out[5] = 0;                                   // flags
    const ss = intToSyncSafe(framesLen + padding);
    out[6] = ss[0]; out[7] = ss[1]; out[8] = ss[2]; out[9] = ss[3];

    let p = 10;
    for (const f of frames) { out.set(f, p); p += f.length; }
    // padding 区已是 0
    if (audioStart < u8.length) out.set(u8.subarray(audioStart), tagLen);
    return out.buffer;
  }

  return { read, write, FIELDS };
});
