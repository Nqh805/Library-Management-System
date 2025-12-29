# app_logic/models.py
# =========================================================
# FILE MODELS
# Định nghĩa các lớp (classes) đại diện cho cấu trúc dữ liệu chính
# được sử dụng trong ứng dụng, đặc biệt là cho việc quản lý người dùng
# với Flask-Login.
# =========================================================

from flask_login import (
    UserMixin,
)
import mysql  # Lớp cơ sở (mixin) cung cấp các thuộc tính và phương thức cần thiết cho Flask-Login (is_authenticated, is_active, etc.)
from app_logic.db import get_db_connection  # Nhập hàm tạo kết nối CSDL


# =========================================================
# CLASS: User
# Đại diện cho một người dùng (Thành viên) trong hệ thống.
# Kế thừa từ UserMixin để tương thích với Flask-Login.
# =========================================================
class User(UserMixin):
    """
    Lớp đại diện cho một người dùng trong hệ thống.
    Chứa các thông tin cơ bản và các phương thức tĩnh để truy vấn người dùng từ CSDL.
    """

    # -----------------------------------------------------
    # Phương thức khởi tạo (__init__)
    # -----------------------------------------------------
    def __init__(self, id, ho_ten, email, vai_tro, avatar, trang_thai):
        """
        Khởi tạo một đối tượng User.
        Các tham số tương ứng với các cột trong bảng ThanhVien.
        """
        self.id = id  # ID của người dùng (khóa chính, dùng bởi Flask-Login)
        self.ho_ten = ho_ten  # Họ tên
        self.email = email  # Địa chỉ email
        self.vai_tro = vai_tro  # Vai trò ('doc_gia' hoặc 'quan_ly')
        self.avatar = (
            avatar  # Tên file ảnh đại diện (vd: 'abc.jpg' hoặc 'default_avatar.png')
        )
        self.trang_thai = trang_thai  # Trạng thái ('hoat_dong' hoặc 'da_khoa')

    # -----------------------------------------------------
    # Phương thức tĩnh: get
    # Lấy thông tin người dùng từ CSDL dựa trên ID.
    # Được sử dụng bởi `load_user_callback`.
    # -----------------------------------------------------
    @staticmethod
    def get(user_id):
        """
        Truy vấn CSDL để lấy thông tin người dùng dựa trên user_id.
        Trả về một đối tượng User nếu tìm thấy, ngược lại trả về None.
        """
        conn = get_db_connection()
        cursor = conn.cursor(
            dictionary=True
        )  # Dùng dictionary=True để truy cập kết quả theo tên cột
        try:
            # Truy vấn thông tin cơ bản của thành viên
            cursor.execute(
                "SELECT id_thanh_vien, ho_ten, email, vai_tro, avatar, trang_thai FROM ThanhVien WHERE id_thanh_vien = %s",
                (user_id,),
            )
            user_data = cursor.fetchone()  # Lấy một bản ghi kết quả

            if user_data:
                # Nếu tìm thấy user, tạo và trả về đối tượng User
                # Xử lý trường hợp avatar là NULL trong CSDL -> dùng ảnh mặc định
                avatar_path = user_data.get("avatar") or "default_avatar.png"
                return User(
                    id=user_data["id_thanh_vien"],
                    ho_ten=user_data["ho_ten"],
                    email=user_data["email"],
                    vai_tro=user_data["vai_tro"],
                    avatar=avatar_path,
                    trang_thai=user_data["trang_thai"],
                )
            # Nếu không tìm thấy user
            return None
        except mysql.connector.Error as err:  # Bắt lỗi CSDL
            print(f"!!! Lỗi DB khi User.get({user_id}): {err}")
            return None  # Trả về None nếu có lỗi
        finally:
            # Đảm bảo đóng kết nối và cursor
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    # -----------------------------------------------------
    # Phương thức tĩnh: get_by_email
    # Lấy thông tin người dùng từ CSDL dựa trên địa chỉ email.
    # Được sử dụng trong quá trình đăng nhập.
    # -----------------------------------------------------
    @staticmethod
    def get_by_email(email):
        """
        Truy vấn CSDL để lấy thông tin người dùng (bao gồm cả mật khẩu hash) dựa trên email.
        Trả về một dictionary chứa dữ liệu người dùng nếu tìm thấy, ngược lại trả về None.
        Lưu ý: Trả về dict thay vì đối tượng User vì cần truy cập mật khẩu hash khi đăng nhập.
        """
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Truy vấn thông tin thành viên theo email
            cursor.execute(
                """ SELECT id_thanh_vien, ho_ten, email, mat_khau, vai_tro, avatar, trang_thai
                    FROM ThanhVien WHERE email = %s """,
                (email,),
            )
            user_data = cursor.fetchone()  # Lấy một bản ghi
            return user_data  # Trả về dict dữ liệu (hoặc None nếu không tìm thấy)
        except mysql.connector.Error as err:
            print(f"!!! Lỗi DB khi User.get_by_email({email}): {err}")
            return None
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()


# =========================================================
# HÀM CALLBACK: load_user_callback
# Được đăng ký với Flask-Login (@login_manager.user_loader).
# Flask-Login gọi hàm này để tải lại đối tượng người dùng từ ID
# được lưu trong session trên mỗi request.
# =========================================================
def load_user_callback(user_id):
    """
    Hàm callback được Flask-Login sử dụng để tải thông tin người dùng từ ID.
    Gọi phương thức tĩnh User.get(user_id) để thực hiện việc truy vấn CSDL.
    """
    return User.get(user_id)  # Trả về đối tượng User hoặc None
