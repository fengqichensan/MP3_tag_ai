"""实测 Ollama 调用: 直接向 192.168.2.166 的 gemma4:12b-mlx 发请求并计时。"""

import sys
import time

sys.path.insert(0, ".")
import ai_client as aic

cfg = {
    "provider": "ollama",
    "ollama": {"url": "http://192.168.2.166:11434", "model": "gemma4:12b-mlx"},
}

t0 = time.time()
r = aic.extract("12 - 海阔天空 - Beyond.mp3", cfg)
elapsed = time.time() - t0
print(f"elapsed={elapsed:.1f}s source={r.source} track={r.track!r} title={r.title!r} error={r.error!r}")
