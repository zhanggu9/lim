# Kiwoom RSI Auto Trader

**실행**
1. `settings.json`에서 조건/RSI/매매 설정을 확인한다.
2. `run.bat`을 실행한다.

**설정 포인트**
- `mode`: `paper`(모의) 또는 `live`(실전)
- `condition_index`: 조건식 인덱스(기본 0)
- `ticks_per_candle`: 60틱봉 기준
- `rsi_period`: RSI 기간(기본 14)
- `buy_cash`: 매수 금액(원)
- `cooldown_seconds`: 재매수 쿨다운
- `real_fids`: 실시간 FID 리스트(가격/거래량/체결시간 순서)

**주의**
- `account_password`가 비어 있으면 보유 종목 조회가 실패할 수 있다.
- 모의/실전 서버가 설정과 다르면 주문을 차단한다.
