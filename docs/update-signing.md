# 更新签名与发布

## 密钥

- 公钥：`voiceinput/update.py` 的 `UPDATE_PUBLIC_KEY_B64`（Ed25519 raw public key）。
- 私钥：`keys/update_ed25519.pem`，**不在 Git 仓库内**，必须离线备份并限制权限。
- 私钥丢失后无法为旧版本签发可验证的更新；只能生成新密钥、在新版本中替换公钥，
  旧版本用户需通过完整安装包升级。

生成新密钥（只在轮换时执行）：

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import base64

key = Ed25519PrivateKey.generate()
open("keys/update_ed25519.pem", "wb").write(
    key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
)
print(base64.b64encode(
    key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
).decode())
```

把输出的公钥写入 `voiceinput/update.py`，并随新版本发布。

## 发布流程

1. 构建完整包与增量包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 -NoModels
```

2. 生成签名更新清单：

```powershell
python scripts\make_update_manifest.py --version 1.2.0 `
  --update-exe release\LocalVoiceInput-Update-x64.exe `
  --full-exe release\LocalVoiceInput-Setup-x64.exe `
  --out release\update.json
```

3. 创建 GitHub Release，上传：
   - `LocalVoiceInput-Setup-x64.exe`
   - `LocalVoiceInput-Update-x64.exe`
   - `ReleaseNotes.md`
   - `SHA256SUMS.txt` / `SHA256SUMS-update.txt`
   - `update.json`

4. 确认 `releases/latest/download/update.json` 可访问；应用默认读取该地址。

## 模型集变更

- 修改 `voiceinput/paths.py` 的 `MODEL_SET`，并重新生成 `models/model-set.txt` 与 manifest。
- 同步修改 `packaging/installer.iss` 的 `RequiredModelSet`。
- 模型集变化必须发完整安装包；增量包会被拒绝。

## 安全边界

- 清单签名只覆盖清单字段；安装包再由 SHA-256 校验，两者都通过才执行。
- 更新下载仅在用户点击“检查更新”时联网；核心 ASR/LLM 不联网。
- 私钥泄露时立即轮换公钥并发布安全公告。
