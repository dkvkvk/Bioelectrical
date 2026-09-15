> **构建状态**：[![构建桌面安装包](../../actions/workflows/build-desktop.yml/badge.svg)](../../actions/workflows/build-desktop.yml)

# 心电HRV采集分析 —— 云端构建说明

本项目的桌面安装包**全部在 GitHub Actions 云端构建，本地不做打包**。

## 发布新版本（两步）

1. 改代码（如果发布新版本，改 `host_app/core/version.py` 里的版本号）
2. 推送到 GitHub：
   - 日常改动：推到 `main` 分支 → 自动构建 → 在仓库页面
     **Actions → 对应运行记录 → Artifacts** 下载安装包
   - 正式发版：打标签 `git tag v1.0.1 && git push --tags`
     → 自动构建并创建 **Releases 发布页**，安装包挂在发布页上，
     任何人可下载

## 构建产物

| 平台 | 产物 | 说明 |
|---|---|---|
| Windows | `HeartHRV-Setup-vX.Y.Z.exe` | 双击安装的正式安装包（含许可协议页、快捷方式、卸载），安装向导为中文 |
| macOS | `HeartHRV-macOS-vX.Y.Z.zip` | 解压得到 HeartHRV.app（未签名，首次打开需右键→打开） |
| Linux | `HeartHRV-Linux-vX.Y.Z.tar.gz` | 解压后运行 `./HeartHRV/HeartHRV` |

## 构建流程（工作流自动完成）

1. Windows：PyInstaller 打包 exe → **自动运行自检验证exe可用** →
   Inno Setup 封装成安装包
2. macOS / Linux：PyInstaller 打包 + 自检 → 压缩
3. 打了 `v*` 标签时：三个平台产物自动汇总到 Releases 发布页

## 相关文件

- `host_app/packaging/HeartHRV.spec` —— PyInstaller 打包配置
- `host_app/packaging/installer.iss` —— Inno Setup 安装包脚本（含EULA）
- `host_app/packaging/EULA.txt` —— 许可协议文本（发版前可自行修改措辞）
- `host_app/packaging/make_icon.py` —— 图标生成脚本（改图标时本地跑一次后提交产物）

## 注意

- 未购买代码签名证书前，用户首次运行 Windows 安装包会出现蓝色
  SmartScreen 提示，点"更多信息→仍要运行"即可；macOS 需右键→打开。
  这是未签名软件的正常现象，不影响使用。
