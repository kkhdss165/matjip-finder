#!/usr/bin/env bash
# 맛집 검색기 서버 종료
cd "$(dirname "$0")"

PID_FILE=".server.pid"
stopped=0

# 1) PID 파일 기준 종료
if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null && echo "서버 종료 (PID $PID)" && stopped=1
  fi
  rm -f "$PID_FILE"
fi

# 2) 혹시 남은 서버 프로세스(디버그 리로더 자식 등) 정리
for p in $(pgrep -f "app.server" 2>/dev/null); do
  kill "$p" 2>/dev/null && echo "잔여 프로세스 종료 (PID $p)" && stopped=1
done

[ "$stopped" -eq 1 ] || echo "실행 중인 서버가 없습니다."
