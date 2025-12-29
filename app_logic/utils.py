# app_logic/utils.py
# =========================================================
# FILE UTILS (Tiện ích)
# Chứa các hàm trợ giúp (helper functions) và decorators được sử dụng
# lặp lại ở nhiều nơi khác nhau trong ứng dụng.
# Việc tách các hàm này ra giúp code gọn gàng, dễ bảo trì và tái sử dụng.
# =========================================================

import unicodedata  # Module xử lý Unicode (dùng để bỏ dấu tiếng Việt)
import re  # Module biểu thức chính quy (Regular Expressions)
from functools import wraps  # Dùng để tạo decorator (cho admin_required)
from flask import flash, redirect, url_for, current_app  # Các hàm tiện ích của Flask
from flask_login import current_user  # Đối tượng đại diện cho người dùng đang đăng nhập


# =========================================================
# HÀM: SLUGIFY
# Chuyển đổi chuỗi thành dạng slug (thân thiện với URL).
# =========================================================
def slugify(value):
    """
    Chuyển đổi văn bản (có dấu tiếng Việt) thành slug an toàn cho URL.
    Loại bỏ dấu, chuyển thành chữ thường, thay khoảng trắng bằng gạch nối,
    xóa các ký tự không hợp lệ.
    Ví dụ: "Mắt Biếc" -> "mat-biec", "Lập Trình Web 101" -> "lap-trinh-web-101"
    """
    if value is None:
        return ""  # Trả về chuỗi rỗng nếu đầu vào là None
    value = str(value)  # Đảm bảo đầu vào là chuỗi
    value = value.replace("Đ", "D").replace("đ", "d")  # Thay thế chữ Đ/đ
    value = unicodedata.normalize("NFD", value)  # Chuẩn hóa Unicode NFD để tách dấu
    # Loại bỏ các ký tự dấu (Mark, Nonspacing)
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    value = value.lower()  # Chuyển thành chữ thường
    # Xóa các ký tự không phải chữ cái, số, khoảng trắng hoặc gạch nối
    value = re.sub(r"[^a-z0-9\s-]", "", value).strip()
    # Thay thế một hoặc nhiều khoảng trắng/gạch nối liên tiếp bằng một gạch nối duy nhất
    value = re.sub(r"[-\s]+", "-", value)
    return value


# =========================================================
# HÀM: ALLOWED_FILE
# Kiểm tra xem tên file có đuôi mở rộng hợp lệ (được phép upload) hay không.
# =========================================================
def allowed_file(filename):
    """
    Kiểm tra phần đuôi của tên file có nằm trong danh sách ALLOWED_EXTENSIONS
    được định nghĩa trong cấu hình ứng dụng (app.config) hay không.
    Trả về True nếu hợp lệ, False nếu không hợp lệ.
    """
    # Lấy danh sách đuôi file cho phép từ config, nếu không có thì dùng set rỗng
    allowed_exts = current_app.config.get("ALLOWED_EXTENSIONS", set())
    # Kiểm tra xem tên file có chứa dấu '.' VÀ phần đuôi (sau dấu '.' cuối cùng)
    # sau khi chuyển thành chữ thường, có nằm trong danh sách allowed_exts không.
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_exts


# =========================================================
# DECORATOR: ADMIN_REQUIRED
# Dùng để bảo vệ các route, chỉ cho phép admin (vai_tro='quan_ly') truy cập.
# =========================================================
def admin_required(f):
    """
    Decorator để kiểm tra quyền admin trước khi thực thi một view function.
    Nếu người dùng chưa đăng nhập hoặc không phải admin, sẽ flash thông báo lỗi
    và chuyển hướng về trang chủ của người dùng (core.index).
    """

    @wraps(f)  # Giữ lại thông tin của hàm gốc (f)
    def decorated_function(*args, **kwargs):
        # Kiểm tra: Chưa đăng nhập HOẶC vai trò không phải 'quan_ly'
        if not current_user.is_authenticated or current_user.vai_tro != "quan_ly":
            flash("Bạn không có quyền truy cập trang này.", "danger")  # Thông báo lỗi
            return redirect(url_for("core.index"))  # Chuyển hướng về trang chủ
        # Nếu là admin, cho phép thực thi hàm gốc
        return f(*args, **kwargs)

    return decorated_function


# =========================================================
# HÀM: GET_OR_CREATE
# Lấy ID của một bản ghi dựa trên giá trị cột tên (vd: tên tác giả),
# hoặc tạo mới bản ghi nếu chưa tồn tại và trả về ID mới.
# =========================================================
def get_or_create(cursor, table, id_column, name_column, value):
    """
    Kiểm tra nếu một giá trị (`value`) đã tồn tại trong cột `name_column` của bảng `table`.
    - Nếu tồn tại, trả về giá trị của cột `id_column`.
    - Nếu không tồn tại, tạo một bản ghi mới với giá trị `value` trong cột `name_column`
      và trả về ID của bản ghi mới được tạo (lastrowid).
    Hữu ích khi thêm sách để xử lý Tác giả/Thể loại mới hoặc đã có.
    So sánh tên không phân biệt hoa thường.
    """
    clean_value = value.strip()  # Loại bỏ khoảng trắng thừa ở đầu/cuối
    if not clean_value:
        return None  # Trả về None nếu giá trị rỗng

    # Truy vấn tìm ID dựa trên tên (không phân biệt hoa thường)
    query = f"SELECT {id_column} FROM {table} WHERE LOWER({name_column}) = LOWER(%s)"  # Sửa: Thêm LOWER()
    cursor.execute(query, (clean_value,))  # Bỏ .lower() ở đây vì đã có trong query
    result = cursor.fetchone()

    if result:
        # Nếu tìm thấy, trả về ID (lấy theo tên cột id_column)
        return result[id_column]
    else:
        # Nếu không tìm thấy, tạo bản ghi mới
        insert_query = f"INSERT INTO {table} ({name_column}) VALUES (%s)"
        cursor.execute(insert_query, (clean_value,))
        return cursor.lastrowid  # Trả về ID của bản ghi vừa được thêm


# =========================================================
# HÀM: GHI_NHAT_KY_ADMIN
# Ghi lại hành động của admin vào bảng AdminLog.
# =========================================================
def ghi_nhat_ky_admin(cursor, hanh_dong):
    """
    Thêm một bản ghi vào bảng AdminLog để lưu lại hành động (`hanh_dong`)
    của quản trị viên đang đăng nhập (`current_user.id`).
    Sử dụng try-except để tránh làm dừng chương trình chính nếu ghi log thất bại.
    """
    try:
        # Thêm log vào bảng AdminLog
        cursor.execute(
            "INSERT INTO AdminLog (id_admin, hanh_dong) VALUES (%s, %s)",
            (current_user.id, hanh_dong),
        )
        # Lưu ý: conn.commit() cần được gọi ở hàm gọi hàm này, sau khi các thao tác chính thành công.
    except Exception as e:
        # In ra lỗi nếu không ghi được log, nhưng không dừng chương trình
        print(f"!!! LOI GHI NHAT KY ADMIN: {e}")
