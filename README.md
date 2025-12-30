# Hệ thống Quản lý Thư viện (Library Management System)

Đây là dự án thiết kế và xây dựng cơ sở dữ liệu cho hệ thống thư viện, phục vụ việc quản lý sách, độc giả và phiếu mượn trả.

## 🛠 Công nghệ sử dụng
* **Database:** MySQL
* **Design Tool:** Draw.io (vẽ ERD), MySQL Workbench
* **Ngôn ngữ hỗ trợ:** Python (xử lý dữ liệu/kết nối)

## 📋 Tính năng chính (Database)
* Thiết kế sơ đồ UseCase, sơ đồ thực thể liên kết (ERD) và ánh xạ sang mô hình quan hệ.
* Cơ sở dữ liệu chuẩn hóa tới dạng chuẩn 3 (3NF): Đảm bảo dữ liệu nguyên tố, phụ thuộc đầy đủ vào khóa chính, và không chứa phụ thuộc bắc cầu, bảo đảm tính toàn vẹn dữ liệu.
* **Quản lý quan hệ phức tạp:** Xử lý mối quan hệ Nhiều - Nhiều (N-N) giữa Sách - Tác giả - Thể loại.
* **Ràng buộc dữ liệu chặt chẽ:** Sử dụng Foreign Key (ON DELETE RESTRICT/CASCADE) để đảm bảo không xảy ra lỗi orphan data (dữ liệu mồ côi) khi thao tác xóa/sửa.
* **Truy vấn hiệu quả:** Cấu trúc bảng được tối ưu để phục vụ các tác vụ tìm kiếm sách và thống kê mượn trả nhanh chóng.
* Các bảng chính: Sách, Độc giả, Mượn trả, Tác giả.

## 📸 Sơ đồ UseCase

<img width="949" height="816" alt="Screenshot 2025-10-29 230625" src="https://github.com/user-attachments/assets/74d74e5b-267a-476b-9fba-e679aef87fff" />


## 📸 Sơ đồ ERD

<img width="1474" height="829" alt="Screenshot 2025-12-29 225617" src="https://github.com/user-attachments/assets/c2ebaf19-1729-4307-a8e2-acc2946a88cb" />

