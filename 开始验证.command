#!/bin/zsh
cd -- "${0:A:h}" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
python3 -B scripts/demo.py --open
result=$?
printf '\n按回车关闭窗口。'
read -r reply
exit "$result"
