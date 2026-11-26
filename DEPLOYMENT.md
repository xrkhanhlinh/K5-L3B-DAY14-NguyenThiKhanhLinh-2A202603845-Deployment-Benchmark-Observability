# Deployment Information

## Public URL
https://k5-day14-agent-m1o9.onrender.com

## Platform
Render, gói free, region Singapore.
- Web service: `k5-day14-agent`, ID `srv-dc46dmuc6qcc73ckqn50`.
- Redis: `day14-redis`, ID `red-dc46d5vlk1mc739ose30`, trạng thái available.
- Deploy `dep-dc46dn6c6qcc73ckqo7g` từ commit `05e445e536b6dabc20542682a8b8493518947e9e` đã chuyển sang `live`.
- CLI xác thực do học viên trực tiếp Authorize CLI; không lưu CLI token trong repo.

## Kết quả kiểm tra thật
Chạy curl sau khi service live, ngày 27/11/2026 (GMT+7):
```text
health=200
ready=200
ask_without_key=401
ask_with_key=200
```
Log Render sau deploy có các dòng JSON của agent và request /health trả 200.

## Cấu hình đã đặt trên Render
- Root directory: `06-lab-complete`.
- Runtime: Docker; Docker context `.`, Dockerfile `./Dockerfile`.
- Health check: `/health`.
- `AGENT_API_KEY`: key ngẫu nhiên được đặt qua CLI, giá trị giữ ngoài Git.
- `REDIS_URL`: internalConnectionString của Redis cùng region.
- `ENVIRONMENT=production`.
- `RATE_LIMIT_PER_MINUTE=10`.
- `DAILY_BUDGET_USD=1`.
- `PORT`: Render cấp; Docker CMD đọc PORT.
- Redis gói free có persistence off; state chia sẻ giữa worker và còn khi restart agent, nhưng không cam kết giữ dữ liệu qua restart Redis. Với production thật cần gói có persistence.

Service được tạo trực tiếp bằng CLI từ repo/main. File `06-lab-complete/render.yaml` cung cấp phương án Blueprint tương đương: đặt Blueprint path là `06-lab-complete/render.yaml`; file đã khai báo rootDir đúng monorepo. Blueprint generateValue có thể sinh key riêng khi tạo service mới.

## Lệnh tự kiểm tra
Trong Bash, đặt BASE là URL bên trên, AGENT_API_KEY lấy từ env của service:
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
```

## Bằng chứng ảnh còn thiếu
`screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png` chưa được chụp. Công cụ điều khiển trình duyệt timeout; chưa dùng ảnh giả thay thế.

Tham khảo cấu hình: [Render Blueprint specification](https://render.com/docs/blueprint-spec).
