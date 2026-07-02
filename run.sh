#!/usr/bin/env bash
# 맛집 검색기 서버 실행 (백그라운드). 종료는 ./stop.sh
set -e
cd "$(dirname "$0")"

PID_FILE=".server.pid"
# settings.yaml 의 server.port 값만 읽어 URL 구성 (없으면 5001)
PORT=$(awk '/^server:/{f=1} f&&/^[[:space:]]*port:/{v=$2; gsub(/[^0-9]/,"",v); print v; exit}' config/settings.yaml)
PORT=${PORT:-5001}
URL="http://127.0.0.1:$PORT"

# 이미 실행 중이면 중복 실행 방지
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "이미 실행 중입니다 (PID $(cat "$PID_FILE")). 종료: ./stop.sh"
  echo "→ $URL"
  exit 0
fi

# 가상환경 없으면 생성 + 설치
if [ ! -x ".venv/bin/python" ]; then
  echo "가상환경(.venv)이 없어 생성합니다..."
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
  ./.venv/bin/playwright install chromium
fi

# 비밀 설정 파일 안내
if [ ! -f "config/settings.local.yaml" ]; then
  echo "⚠️  config/settings.local.yaml 이 없습니다. 예시를 복사합니다 → 카카오 REST 키를 채우세요."
  cp config/settings.local.yaml.example config/settings.local.yaml
fi

# 백그라운드 실행 (로그는 server.log)
nohup ./.venv/bin/python -m app.server > server.log 2>&1 &
echo $! > "$PID_FILE"
sleep 2

if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "✅ 서버 시작 (PID $(cat "$PID_FILE"))"
  echo "   → $URL"
  echo "   로그: tail -f server.log   |   종료: ./stop.sh"
else
  echo "❌ 시작 실패. server.log 를 확인하세요:"
  tail -n 20 server.log
  rm -f "$PID_FILE"
  exit 1
fi
