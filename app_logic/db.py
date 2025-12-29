# app_logic/db.py
# =========================================================
# FILE DB CONNECTION
# Chứa cấu hình kết nối đến cơ sở dữ liệu MySQL và cung cấp
# một hàm (`get_db_connection`) để tạo và trả về một đối tượng kết nối.
# Cấu hình được lấy từ các biến môi trường để tăng tính bảo mật
# và linh hoạt khi triển khai.
# =========================================================
from dotenv import load_dotenv # Nhập hàm
load_dotenv() # Tải các biến từ file .env
import os  # Module thao tác với hệ điều hành (để đọc biến môi trường)
import mysql.connector  # Thư viện chính thức của MySQL để kết nối Python với MySQL

# --- Cấu hình kết nối Database ---
# Lấy thông tin kết nối (host, user, password, tên database) từ các biến môi trường.
# Các biến này thường được định nghĩa trong file .env và được tải bởi thư viện python-dotenv.
# Việc này giúp giữ thông tin nhạy cảm tách biệt khỏi mã nguồn.
db_config = {
    "host": os.getenv(
        "DB_HOST", "localhost"
    ),  # Host database (mặc định là localhost nếu không có biến môi trường)
    "user": os.getenv("DB_USER", "root"),  # Tên người dùng database
    "password": os.getenv("DB_PASSWORD", "1234"),  # Mật khẩu database
    "database": os.getenv("DB_NAME", "lms"),  # Tên database
    # Có thể thêm các cấu hình khác nếu cần, ví dụ: port, charset='utf8mb4'
}


# =========================================================
# HÀM: GET_DB_CONNECTION
# Tạo và trả về một kết nối mới đến cơ sở dữ liệu MySQL.
# =========================================================
def get_db_connection():
    """
    Tạo một kết nối mới đến cơ sở dữ liệu MySQL sử dụng cấu hình trong `db_config`.
    Trả về: Đối tượng connection của mysql.connector.
    Lưu ý: Hàm này tạo kết nối mới mỗi khi được gọi. Việc quản lý
           (đóng) kết nối cần được thực hiện ở nơi gọi hàm này (thường trong khối finally).
    """
    # Sử dụng toán tử ** để giải nén dict db_config thành các tham số keyword cho hàm connect
    conn = mysql.connector.connect(**db_config)
    return conn  # Trả về đối tượng kết nối
