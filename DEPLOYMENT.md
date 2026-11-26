# Deployment Information

## Trạng thái
Chọn Render; đã đăng nhập Render CLI thành công sau lần thử lại.
Chưa có URL public được kiểm chứng. Cấu hình deploy không thay thế bằng chứng service đã chạy.

## Cấu hình
- Blueprint path: `06-lab-complete/render.yaml`.
- Root directory: `06-lab-complete`.
- Docker context: `.`; Dockerfile: `./Dockerfile`, tính từ root directory.
- Web service + Redis cùng region Singapore.
- Health check: `/health`.
- `AGENT_API_KEY`: Render generateValue; không ghi giá trị thật vào Git.
- `REDIS_URL`: connectionString của Redis.
- `ENVIRONMENT=production`, `RATE_LIMIT_PER_MINUTE=10`, `DAILY_BUDGET_USD=1`.
- `PORT`: nền tảng cấp; Docker CMD đọc PORT.

## Tự kiểm tra
Trong Bash, BASE là URL service; AGENT_API_KEY lấy từ env của service:
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
```
Kỳ vọng: 200 / 200 / 401 / 200. Chưa ghi nhận kết quả cloud.

## Bằng chứng còn thiếu
`screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`: cần chụp service thật và che secrets.

Cấu hình đường dẫn theo [Render Blueprint specification](https://render.com/docs/blueprint-spec).
