# CLAUDE.md — EC Advanced Learners' Dictionary

**Trước khi làm gì, đọc `STATUS.md`** (trạng thái hiện tại, việc cần làm tiếp, lệnh chạy, bẫy đã gặp).
Cập nhật `STATUS.md` mỗi khi trạng thái đổi: xong một vòng, chạy/dừng đợt Gemini, người dùng chốt quyết định mới,
và trước khi kết thúc một chặng làm việc dài.

## Quy tắc bắt buộc

- Trả lời người dùng bằng tiếng Việt. File để người dùng xem lưu ở `_deliverables/`.
- Làm theo skill `use-case-a-z`: `use-cases.md` là nguồn sự thật; tính năng mới phải thêm use case trước (Phase 5:
  kiểm tra xung đột rồi mới code); sau mỗi vòng ghi phần tự kiểm vào `PLAN.md`.
- Không đưa vào dữ liệu nguồn ngoài `pipeline/sources.toml`; không chứa nội dung Oxford/Cambridge/Longman/Collins/Merriam-Webster/EVP.
- Nội dung AI luôn có nhãn AI và nằm ở dòng riêng (`is_ai=1`, layer `learner`), không ghi đè nghĩa Wiktionary.
- `khoa-api.env`: không in khoá, không commit; không xoay vòng khoá free để nhân quota.
- Không điều khiển chuột/bàn phím trên màn hình người dùng; thử giao diện bằng trình duyệt riêng + `app/dev-bridge.py`
  với file dữ liệu cá nhân tạm (`TUDIEN_USER_DB`), không ghi vào dữ liệu thật của người dùng.
- Không cài phần mềm, không đổi cài đặt hệ thống thay người dùng (hướng dẫn họ tự làm).
