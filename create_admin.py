# create_admin.py
# =========================================================
# SCRIPT TẠO TÀI KHOẢN ADMIN (QUẢN LÝ)
# Chạy script này từ dòng lệnh (python create_admin.py)
# để tạo một tài khoản người dùng ban đầu với vai trò 'quan_ly'.
# Script sẽ yêu cầu nhập Họ tên, Email, Mật khẩu (ẩn khi gõ)
# và thêm người dùng vào bảng ThanhVien trong CSDL.
# Cấu hình CSDL được đọc từ file .env.
# =========================================================

import mysql.connector # Thư viện kết nối MySQL
import datetime # Module xử lý ngày tháng (lấy ngày đăng ký)
from werkzeug.security import generate_password_hash # Hàm hash mật khẩu
import getpass  # Thư viện để nhập mật khẩu an toàn (ẩn khi gõ trên terminal)
import os  # Module thao tác với hệ điều hành (để đọc biến môi trường)
from dotenv import load_dotenv  # Thư viện tải biến môi trường từ file .env

# Tải các biến môi trường từ file .env (chứa cấu hình DB)
load_dotenv()

# --- Cấu hình Database (Đọc từ file .env) ---
# Lấy thông tin kết nối CSDL từ các biến môi trường đã tải
db_config = {
    "host": os.getenv("DB_HOST", "localhost"), # Host (mặc định localhost)
    "user": os.getenv("DB_USER", "root"),      # User
    "password": os.getenv("DB_PASSWORD", "1234"), # Password
    "database": os.getenv("DB_NAME", "lms"), # Tên DB
}

# =========================================================
# HÀM: create_super_admin
# Chức năng chính của script: lấy thông tin, tạo admin.
# =========================================================
def create_super_admin():
    """Hàm chính để thực hiện việc tạo tài khoản Super Admin."""
    conn = None # Khởi tạo biến connection bên ngoài try để finally có thể truy cập
    cursor = None # Khởi tạo biến cursor
    try:
        print("--- Bắt đầu tạo tài khoản Super Admin ---")
        # --- Lấy thông tin từ người dùng ---
        ho_ten = input("Nhập Họ và Tên: ").strip() # Dùng input() để lấy họ tên
        email = input("Nhập Email: ").strip()      # Lấy email
        # Dùng getpass.getpass() để nhập mật khẩu mà không hiển thị ký tự trên màn hình
        password = getpass.getpass("Nhập Mật khẩu: ")
        password_confirm = getpass.getpass("Xác nhận Mật khẩu: ")

        # --- Validation cơ bản ---
        # Kiểm tra mật khẩu khớp
        if password != password_confirm:
            print("❌ Lỗi: Mật khẩu không khớp. Vui lòng thử lại.")
            return # Dừng thực thi
        # Kiểm tra thông tin rỗng
        if not all([ho_ten, email, password]):
            print("❌ Lỗi: Vui lòng không để trống thông tin.")
            return

        # --- Kết nối CSDL và xử lý ---
        conn = mysql.connector.connect(**db_config) # Tạo kết nối CSDL
        cursor = conn.cursor() # Tạo đối tượng cursor để thực thi lệnh SQL

        # Kiểm tra xem email đã tồn tại trong bảng ThanhVien chưa
        cursor.execute("SELECT email FROM ThanhVien WHERE email = %s", (email,))
        if cursor.fetchone(): # Nếu fetchone() trả về kết quả -> email đã tồn tại
            print(f"❌ Lỗi: Email '{email}' đã tồn tại.")
            return # Dừng nếu email trùng

        # --- Chuẩn bị dữ liệu để INSERT ---
        hashed_password = generate_password_hash(password) # Hash mật khẩu nhập vào
        ngay_dang_ky = datetime.date.today() # Lấy ngày hiện tại làm ngày đăng ký
        vai_tro = "quan_ly" # Đặt vai trò là quản lý
        trang_thai = "hoat_dong"  # Đặt trạng thái mặc định là hoạt động

        # --- Thêm admin vào CSDL ---
        # Câu lệnh INSERT với đủ các cột cần thiết
        insert_query = """
            INSERT INTO ThanhVien (ho_ten, email, mat_khau, vai_tro, ngay_dang_ky, trang_thai)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (ho_ten, email, hashed_password, vai_tro, ngay_dang_ky, trang_thai))
        conn.commit() # Lưu thay đổi vào CSDL

        # --- Thông báo thành công ---
        print("\n✅ Thành công! Tài khoản Super Admin đã được tạo.")
        print(f"   - Tên: {ho_ten}")
        print(f"   - Email: {email}")

    except mysql.connector.Error as err:
        # Xử lý nếu có lỗi CSDL xảy ra
        print(f"❌ Lỗi Database: {err}")
        if conn: conn.rollback() # Hoàn tác thay đổi nếu có lỗi
    except Exception as e:
         # Xử lý các lỗi không mong muốn khác
         print(f"❌ Lỗi không xác định: {e}")
         if conn: conn.rollback()
    finally:
        # --- Dọn dẹp ---
        # Đảm bảo đóng cursor và connection sau khi hoàn thành (dù thành công hay lỗi)
        if cursor:
            cursor.close()
        # Kiểm tra xem conn đã được khởi tạo và đang kết nối trước khi đóng
        if conn and conn.is_connected():
            conn.close()
            print("--- Đã đóng kết nối CSDL ---")

# =========================================================
# ĐIỂM BẮT ĐẦU THỰC THI SCRIPT
# =========================================================
if __name__ == "__main__":
    # Khối này chỉ chạy khi script được thực thi trực tiếp (python create_admin.py)
    # mà không chạy khi được import như một module vào file khác.
    create_super_admin() # Gọi hàm chính để bắt đầu quá trình tạo admin