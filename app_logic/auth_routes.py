# app_logic/auth_routes.py
# =========================================================
# FILE AUTH ROUTES
# Chứa các route liên quan đến xác thực người dùng:
# - Đăng ký tài khoản mới (/register)
# - Đăng nhập (/login)
# - Đăng xuất (/logout)
# Sử dụng Flask-Login để quản lý session đăng nhập.
# =========================================================

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import (
    login_required,
    login_user,
    logout_user,
    current_user,
)  # Các hàm quản lý session đăng nhập
from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)  # Hàm hash và kiểm tra mật khẩu
from app_logic.models import User  # Import lớp User từ models.py
from app_logic.db import get_db_connection  # Import hàm kết nối CSDL
import mysql.connector  # Import để xử lý lỗi CSDL cụ thể

# Tạo Blueprint cho các route xác thực
# Không cần url_prefix vì các route như /login, /register nằm ở gốc
auth_bp = Blueprint("auth", __name__, template_folder="templates")


# =========================================================
# ROUTE: ĐĂNG KÝ TÀI KHOẢN ("/register")
# =========================================================
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """
    Hiển thị form đăng ký (GET) và xử lý đăng ký tài khoản mới (POST).
    Kiểm tra mật khẩu khớp, độ dài mật khẩu, email trùng lặp.
    Hash mật khẩu trước khi lưu vào CSDL.
    Tài khoản mới mặc định là 'doc_gia' và 'hoat_dong'.
    """
    if request.method == "POST":
        # Lấy dữ liệu từ form
        ho_ten = request.form.get("ho_ten", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password")  # Mật khẩu không strip
        confirm_password = request.form.get("confirm_password")

        # --- Validation phía Server ---
        if not all([ho_ten, email, password, confirm_password]):
            flash("Vui lòng điền đầy đủ thông tin.", "danger")
            return redirect(url_for("auth.register"))
        if password != confirm_password:
            flash("Mật khẩu và xác nhận mật khẩu không khớp.", "danger")
            return redirect(url_for("auth.register"))
        if len(password) < 6:
            flash("Mật khẩu phải có ít nhất 6 ký tự.", "danger")
            return redirect(url_for("auth.register"))
        # (Có thể thêm validation định dạng email phức tạp hơn ở đây nếu cần)

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(
                dictionary=True
            )  # Dùng dictionary để kiểm tra fetchone() dễ hơn
            # --- Kiểm tra email đã tồn tại chưa ---
            cursor.execute("SELECT email FROM ThanhVien WHERE email = %s", (email,))
            if cursor.fetchone():  # Nếu fetchone() trả về kết quả -> email đã tồn tại
                flash("Email đã được đăng ký. Vui lòng sử dụng email khác.", "danger")
                return redirect(url_for("auth.register"))  # Quay lại form đăng ký

            # --- Tạo tài khoản mới ---
            # Hash mật khẩu bằng Werkzeug
            hashed_password = generate_password_hash(password)
            # Thiết lập vai trò và trạng thái mặc định cho người dùng mới
            vai_tro = "doc_gia"
            trang_thai = "hoat_dong"

            # Thêm người dùng mới vào CSDL
            cursor.execute(
                "INSERT INTO ThanhVien (ho_ten, email, mat_khau, vai_tro, trang_thai) VALUES (%s, %s, %s, %s, %s)",
                (ho_ten, email, hashed_password, vai_tro, trang_thai),
            )
            conn.commit()  # Lưu thay đổi vào CSDL
            flash(f"Tài khoản đã được tạo thành công! Vui lòng đăng nhập.", "success")
            return redirect(
                url_for("auth.login")
            )  # Chuyển hướng đến trang đăng nhập sau khi thành công

        except mysql.connector.Error as err:
            # Xử lý lỗi CSDL
            if conn:
                conn.rollback()  # Hoàn tác nếu có lỗi
            flash(f"Lỗi khi đăng ký tài khoản: {err}", "danger")
            print(f"!!! Lỗi DB khi đăng ký: {err}")
            return redirect(url_for("auth.register"))  # Quay lại form đăng ký nếu lỗi
        except Exception as e:
            # Xử lý lỗi không mong muốn khác
            if conn:
                conn.rollback()
            flash(f"Lỗi không xác định: {e}", "danger")
            print(f"!!! Lỗi không xác định khi đăng ký: {e}")
            return redirect(url_for("auth.register"))
        finally:
            # Đảm bảo đóng kết nối CSDL sau khi sử dụng xong
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    # Xử lý request GET: Chỉ cần hiển thị template đăng ký
    return render_template("register.html")


# =========================================================
# ROUTE: ĐĂNG NHẬP ("/login")
# =========================================================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    Hiển thị form đăng nhập (GET) và xử lý đăng nhập (POST).
    Kiểm tra email, mật khẩu.
    Kiểm tra trạng thái tài khoản (có bị khóa không).
    Sử dụng Flask-Login để tạo session đăng nhập.
    Chuyển hướng đến trang dashboard (nếu là admin) hoặc trang chủ (nếu là độc giả).
    Hỗ trợ chuyển hướng đến trang 'next' nếu có sau khi đăng nhập thành công.
    """
    # Nếu người dùng đã đăng nhập rồi, chuyển hướng họ đi ngay
    if current_user.is_authenticated:
        if current_user.vai_tro == "quan_ly":
            return redirect(url_for("admin.admin_dashboard"))  # Admin về dashboard
        else:
            return redirect(url_for("core.index"))  # Độc giả về trang chủ

    if request.method == "POST":
        # Lấy email và mật khẩu từ form
        email = request.form.get("email")
        password = request.form.get("password")

        # Kiểm tra xem có thiếu thông tin không
        if not email or not password:
            flash("Vui lòng cung cấp đầy đủ thông tin đăng nhập.", "warning")
            return redirect(url_for("auth.login"))

        # Lấy thông tin người dùng từ CSDL bằng email (sử dụng phương thức static của lớp User)
        # user_data là một dict chứa thông tin user từ CSDL (bao gồm cả mật khẩu hash)
        user_data = User.get_by_email(email)

        # Kiểm tra xem user có tồn tại VÀ mật khẩu nhập vào có khớp với mật khẩu hash trong CSDL không
        if user_data and check_password_hash(user_data["mat_khau"], password):
            # Nếu thông tin đăng nhập đúng, kiểm tra trạng thái tài khoản
            if user_data.get("trang_thai") == "da_khoa":
                # Nếu tài khoản bị khóa, báo lỗi và không cho đăng nhập
                flash(
                    "Tài khoản của bạn đã bị khóa. Vui lòng liên hệ quản trị viên.",
                    "danger",
                )
                return redirect(url_for("auth.login"))
            else:
                # Nếu tài khoản hoạt động, tạo đối tượng User (cần cho Flask-Login)
                user_obj = User(
                    id=user_data["id_thanh_vien"],
                    ho_ten=user_data["ho_ten"],
                    email=user_data["email"],
                    vai_tro=user_data["vai_tro"],
                    avatar=user_data.get("avatar")
                    or "default_avatar.png",  # Xử lý avatar NULL/None
                    trang_thai=user_data.get("trang_thai", "hoat_dong"),
                )
                # Đăng nhập người dùng bằng Flask-Login, hàm này sẽ tạo session cho người dùng
                login_user(user_obj)
                flash(f"Chào mừng {user_obj.ho_ten}!", "success")  # Thông báo chào mừng

                # --- Chuyển hướng sau khi đăng nhập thành công ---
                next_page = request.args.get(
                    "next"
                )  # Lấy tham số 'next' từ URL (nếu có)
                # Flask-Login tự động thêm tham số 'next' khi redirect người dùng chưa đăng nhập
                if next_page:
                    # Ưu tiên chuyển hướng đến trang 'next' nếu nó tồn tại
                    # Cần có thêm kiểm tra để đảm bảo 'next' là URL an toàn (vd: dùng url_has_allowed_host_and_scheme)
                    return redirect(next_page)
                # Nếu không có 'next', chuyển hướng dựa trên vai trò
                elif user_obj.vai_tro == "quan_ly":
                    return redirect(
                        url_for("admin.admin_dashboard")
                    )  # Admin về dashboard
                else:
                    return redirect(url_for("core.index"))  # Độc giả về trang chủ
        else:
            # Nếu email không tồn tại hoặc mật khẩu sai
            flash(
                "Đăng nhập không thành công. Vui lòng kiểm tra lại email và mật khẩu.",
                "danger",
            )
            return redirect(url_for("auth.login"))  # Quay lại trang đăng nhập

    # Xử lý request GET: Hiển thị template form đăng nhập
    return render_template("login.html")


# =========================================================
# ROUTE: ĐĂNG XUẤT ("/logout")
# =========================================================
@auth_bp.route("/logout")
@login_required  # Chỉ người đã đăng nhập mới có thể đăng xuất
def logout():
    """
    Xử lý đăng xuất người dùng.
    Xóa session đăng nhập bằng Flask-Login.
    Chuyển hướng về trang đăng nhập.
    """
    logout_user()  # Hàm của Flask-Login để xóa thông tin người dùng khỏi session
    flash("Bạn đã đăng xuất.", "info")  # Thông báo cho người dùng
    return redirect(url_for("auth.login"))  # Chuyển hướng về trang đăng nhập
