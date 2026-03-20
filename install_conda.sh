#!/bin/bash
# 一键安装 Miniconda 脚本
# 支持 Linux x86_64 / aarch64

set -e

CONDA_DIR="$HOME/miniconda3"
INSTALLER="/tmp/miniconda_installer.sh"

# -------- 颜色输出 --------
info()    { echo -e "\033[32m[INFO]\033[0m  $*"; }
warn()    { echo -e "\033[33m[WARN]\033[0m  $*"; }
error()   { echo -e "\033[31m[ERROR]\033[0m $*"; exit 1; }

# -------- 检测是否已安装 --------
if [ -f "$CONDA_DIR/bin/conda" ]; then
    warn "Conda 已安装于 $CONDA_DIR，跳过安装。"
    warn "如需重装，请先删除该目录：rm -rf $CONDA_DIR"
    exit 0
fi

# -------- 检测系统架构 --------
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)  MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh" ;;
    aarch64) MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh" ;;
    *)       error "不支持的架构：$ARCH" ;;
esac

info "系统架构：$ARCH"
info "安装目录：$CONDA_DIR"
info "下载地址：$MINICONDA_URL"

# -------- 下载安装包 --------
info "正在下载 Miniconda..."

# 优先使用清华镜像（国内速度更快）
TSINGHUA_URL="https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-Linux-${ARCH}.sh"

if curl -fsSL --connect-timeout 5 "$TSINGHUA_URL" -o "$INSTALLER" 2>/dev/null; then
    info "已从清华镜像下载成功"
elif curl -fsSL --connect-timeout 10 "$MINICONDA_URL" -o "$INSTALLER" 2>/dev/null; then
    info "已从官方源下载成功"
elif command -v wget &>/dev/null; then
    wget -q "$MINICONDA_URL" -O "$INSTALLER" || error "下载失败，请检查网络连接"
    info "已使用 wget 从官方源下载成功"
else
    error "下载失败：curl 和 wget 均不可用，或网络不通"
fi

# -------- 执行安装 --------
info "正在安装 Miniconda 到 $CONDA_DIR ..."
bash "$INSTALLER" -b -p "$CONDA_DIR"
rm -f "$INSTALLER"

# -------- 初始化 Shell --------
info "正在初始化 conda..."
"$CONDA_DIR/bin/conda" init bash

# 如果使用 zsh 也一并初始化
if [ -f "$HOME/.zshrc" ]; then
    "$CONDA_DIR/bin/conda" init zsh
    info "已初始化 zsh"
fi

# -------- 配置国内镜像源（可选） --------
info "配置清华镜像源..."
"$CONDA_DIR/bin/conda" config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/
"$CONDA_DIR/bin/conda" config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free/
"$CONDA_DIR/bin/conda" config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/
"$CONDA_DIR/bin/conda" config --set show_channel_urls yes

# -------- 完成 --------
info "=========================================="
info "  Miniconda 安装完成！"
info "=========================================="
info "请执行以下命令使配置生效："
echo ""
echo "    source ~/.bashrc"
echo ""
info "然后验证安装："
echo ""
echo "    conda --version"
echo "    conda info"
echo ""
info "常用命令："
echo "    conda create -n myenv python=3.10   # 创建虚拟环境"
echo "    conda activate myenv                 # 激活环境"
echo "    conda deactivate                     # 退出环境"
