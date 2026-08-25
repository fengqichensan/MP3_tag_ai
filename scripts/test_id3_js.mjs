#!/usr/bin/env node
/*
 * id3.js 与 mutagen 的对拍测试（需要 Node 18+ 和仓库 .venv）。
 * 运行:  node scripts/test_id3_js.mjs
 *
 * 覆盖:
 *   1. mutagen v2.4(UTF-8) / v2.3(UTF-16) 写入 -> ID3Lite.read 读取
 *   2. 无标签文件 -> 读到空串
 *   3. ID3Lite.write 新写标签 -> mutagen 校验（含中文）
 *   4. 在已有标签上改标题、清空专辑 -> mutagen 校验字段增删
 *   5. 音频数据完整性：写入前后非标签区字节一致
 *   6. ID3v1.1 回退读取
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ID3Lite = (await import(path.join(root, "static/id3.js"))).default;
const PY = process.env.PYTHON || path.join(root, ".venv/bin/python");
const helper = path.join(root, "scripts", "id3_test_helper.py");

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "id3test-"));
let failed = 0;

function py(...args) {
  const r = spawnSync(PY, [helper, ...args], { encoding: "utf8" });
  if (r.status !== 0) throw new Error(`python ${args[0]} 失败: ${r.stderr}`);
  return r.stdout.trim();
}
function assertEq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : `\n      got:  ${JSON.stringify(got)}\n      want: ${JSON.stringify(want)}`}`);
  if (!ok) failed++;
}

const SAMPLE = { track: "3/12", title: "凡人修仙传 第2集 七玄门", artist: "忘语", album: "有声书合集" };

// ---- 1. mutagen 写 -> JS 读
for (const ver of ["v2", "v3"]) {
  const f = path.join(tmp, `m_${ver}.mp3`);
  py("make", f, ver);
  assertEq(`read mutagen ${ver}`, ID3Lite.read(fs.readFileSync(f)), SAMPLE);
}

// ---- 2. 无标签 -> 空
const fNone = path.join(tmp, "none.mp3");
py("make", fNone, "none");
assertEq("read no-tag", ID3Lite.read(fs.readFileSync(fNone)),
  { track: "", title: "", artist: "", album: "" });

// ---- 3. JS 写新标签 -> mutagen 校验
const fNew = path.join(tmp, "jsnew.mp3");
fs.copyFileSync(fNone, fNew);
fs.writeFileSync(fNew, Buffer.from(ID3Lite.write(fs.readFileSync(fNew), {
  track: "07", title: "七玄门风云", artist: "朗读者甲", album: "测试专辑",
})));
assertEq("write new tags (mutagen verify)", JSON.parse(py("verify", fNew)),
  { track: "07", title: "七玄门风云", artist: "朗读者甲", album: "测试专辑" });

// ---- 4. 改标题 + 清空专辑 -> mutagen 校验增删
const fMod = path.join(tmp, "m_v2.mp3");
fs.writeFileSync(fMod, Buffer.from(ID3Lite.write(fs.readFileSync(fMod), {
  track: "3/12", title: "新标题", artist: "忘语", album: "",
})));
assertEq("modify/clear (mutagen verify)", JSON.parse(py("verify", fMod)),
  { track: "3/12", title: "新标题", artist: "忘语", album: "" });

// ---- 5. 音频数据完整性（跳过各自标签区后的字节一致）
const before = fs.readFileSync(fNone);
const afterBuf = Buffer.from(ID3Lite.write(before, SAMPLE));
const stripOld = ID3Lite.read(before), tagLenOld = (() => {
  // none.mp3 无标签，直接比较全部音频字节
  return 0;
})();
assertEq("audio bytes preserved",
  afterBuf.subarray(afterBuf.length - before.length).equals(before), true);
void stripOld; void tagLenOld;

// ---- 6. ID3v1.1 回退
const v1 = Buffer.concat([Buffer.alloc(100, 0x41), Buffer.alloc(128, 0)]); // 音频区 junk + 零填充 TAG 块
v1.write("TAG", 100, "latin1");
v1.write("Old Song", 103, "latin1");
v1.write("Old Artist", 133, "latin1");
v1.write("Old Album", 163, "latin1");
v1[226] = 0; v1[227] = 9; // track=9 (v1.1)
assertEq("read id3v1.1", ID3Lite.read(v1),
  { track: "9", title: "Old Song", artist: "Old Artist", album: "Old Album" });

fs.rmSync(tmp, { recursive: true, force: true });
console.log(failed ? `\n${failed} 个断言失败` : "\n全部通过 ✅");
process.exit(failed ? 1 : 0);
