#!/bin/zsh
cd -- "${0:A:h}" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
python3 -B scripts/demo.py --view-latest
result=$?
if (( result != 0 )); then
  printf '\n按回车关闭窗口。'
  read -r reply
fi
exit "$result"
