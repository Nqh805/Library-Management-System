# app_logic/admin_routes.py
# =========================================================
# FILE ADMIN ROUTES
# Chứa tất cả các route dành riêng cho quản trị viên (Admin).
# Các route này đều yêu cầu đăng nhập và có vai trò 'quan_ly'.
# Chúng xử lý các chức năng quản lý cốt lõi của hệ thống thư viện
# như quản lý sách, thành viên, lượt mượn/trả, cài đặt hệ thống.
# Tất cả các route trong file này đều có tiền tố /admin.
# =========================================================

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    current_app,  # Import current_app để truy cập config của ứng dụng Flask hiện tại
)
from flask_login import (
    login_required,
    current_user,
)  # Để kiểm tra đăng nhập và lấy thông tin người dùng
from werkzeug.security import (
    generate_password_hash,
)  # Để hash mật khẩu mới khi admin thêm/reset
from werkzeug.utils import secure_filename  # Để làm sạch tên file upload

# Nhập các hàm trợ giúp và kết nối CSDL từ các module khác
from app_logic.utils import (
    admin_required,  # Decorator kiểm tra quyền admin
    get_or_create,  # Hàm lấy ID hoặc tạo mới (cho tác giả, thể loại)
    ghi_nhat_ky_admin,  # Hàm ghi log hoạt động của admin
    allowed_file,  # Hàm kiểm tra đuôi file hợp lệ
)
from app_logic.db import get_db_connection  # Hàm lấy kết nối CSDL
import datetime  # Để xử lý ngày tháng
import uuid  # Để tạo tên file duy nhất
import math  # Để tính toán phân trang
import os  # Để thao tác với đường dẫn file và thư mục
import mysql.connector  # Để xử lý lỗi CSDL MySQL
import re  # Để sử dụng biểu thức chính quy (vd: chuẩn hóa khoảng trắng)

# Tạo Blueprint cho admin với tiền tố /admin
# template_folder='templates' chỉ định thư mục chứa template (nhưng Flask thường tự tìm)
admin_bp = Blueprint(
    "admin", __name__, template_folder="templates", url_prefix="/admin"
)


# =========================================================
# ROUTE: BẢNG ĐIỀU KHIỂN ADMIN (/admin/dashboard)
# =========================================================
@admin_bp.route("/dashboard")
@login_required  # Yêu cầu đăng nhập
@admin_required  # Yêu cầu quyền admin
def admin_dashboard():
    """
    Hiển thị trang bảng điều khiển chính cho admin.
    Bao gồm các thống kê tổng quan (số sách, thành viên, sách đang mượn, quá hạn, chờ duyệt, tiền phạt),
    danh sách top (sách mượn nhiều, độc giả tích cực, thể loại phổ biến),
    danh sách sách sắp hết hàng, và biểu đồ lượt mượn theo tháng.
    """
    conn = get_db_connection()
    cursor = conn.cursor(
        dictionary=True
    )  # Sử dụng dictionary=True để kết quả trả về dạng dict

    # Khởi tạo các biến thống kê
    total_sach = 0
    total_thanh_vien = 0
    sach_dang_muon = 0
    sach_qua_han = 0
    sach_cho_duyet = 0
    total_phat = 0

    try:
        # Lấy các số liệu thống kê tổng quan từ CSDL
        cursor.execute(
            "SELECT SUM(so_luong) AS total FROM Sach WHERE trang_thai = 'hoat_dong'"
        )
        total_sach = (result := cursor.fetchone()) and result.get("total") or 0

        cursor.execute(
            "SELECT COUNT(*) AS total FROM ThanhVien WHERE trang_thai = 'hoat_dong'"
        )
        total_thanh_vien = (result := cursor.fetchone()) and result.get("total") or 0

        cursor.execute(
            "SELECT SUM(so_luong) AS total FROM MuonTra WHERE trang_thai = 'Đang mượn'"
        )
        sach_dang_muon = (result := cursor.fetchone()) and result.get("total") or 0

        cursor.execute(
            "SELECT SUM(so_luong) AS total FROM MuonTra WHERE trang_thai = 'Đang mượn' AND ngay_hen_tra < CURDATE()"
        )
        sach_qua_han = (result := cursor.fetchone()) and result.get("total") or 0

        cursor.execute(
            "SELECT COUNT(id_muon_tra) AS total FROM MuonTra WHERE trang_thai = 'Đang chờ'"
        )
        sach_cho_duyet = (result := cursor.fetchone()) and result.get("total") or 0

        cursor.execute("SELECT SUM(tien_phat) AS total FROM MuonTra")
        total_phat = (result := cursor.fetchone()) and result.get("total") or 0.0

    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải thống kê dashboard: {err}", "danger")
        # Đặt lại giá trị về 0 nếu có lỗi
        total_sach = total_thanh_vien = sach_dang_muon = sach_qua_han = (
            sach_cho_duyet
        ) = 0
        total_phat = 0.0

    # Gom các thống kê vào dict để truyền cho template
    stats = {
        "total_sach": total_sach,
        "total_thanh_vien": total_thanh_vien,
        "sach_dang_muon": sach_dang_muon,
        "sach_qua_han": sach_qua_han,
        "sach_cho_duyet": sach_cho_duyet,
        "total_phat": total_phat,
    }

    # Lấy dữ liệu cho các danh sách Top 5
    try:
        # Top 5 sách mượn nhiều nhất (chỉ tính lượt đã mượn hoặc đã trả)
        query_top_books = """
        SELECT s.tieu_de, SUM(mt.so_luong) AS total_borrows
        FROM MuonTra mt JOIN Sach s ON mt.id_sach = s.id_sach
        WHERE mt.trang_thai IN ('Đang mượn', 'Đã trả')
        GROUP BY s.id_sach, s.tieu_de ORDER BY total_borrows DESC LIMIT 5
        """
        cursor.execute(query_top_books)
        top_books = cursor.fetchall()

        # Top 5 độc giả mượn nhiều nhất
        query_top_users = """
        SELECT tv.ho_ten, SUM(mt.so_luong) AS total_borrows
        FROM MuonTra mt JOIN ThanhVien tv ON mt.id_thanh_vien = tv.id_thanh_vien
        WHERE mt.trang_thai IN ('Đang mượn', 'Đã trả')
        GROUP BY tv.id_thanh_vien, tv.ho_ten ORDER BY total_borrows DESC LIMIT 5
        """
        cursor.execute(query_top_users)
        top_users = cursor.fetchall()

        # Top 5 thể loại phổ biến nhất
        query_top_genres = """
        SELECT tl.ten_the_loai, SUM(mt.so_luong) AS total_borrows
        FROM MuonTra mt JOIN Sach s ON mt.id_sach = s.id_sach JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai
        WHERE mt.trang_thai IN ('Đang mượn', 'Đã trả')
        GROUP BY tl.id_the_loai, tl.ten_the_loai ORDER BY total_borrows DESC LIMIT 5
        """
        cursor.execute(query_top_genres)
        top_genres = cursor.fetchall()

        # Sách sắp hết hàng (số lượng thực tế còn 1-4 cuốn)
        # Số lượng thực tế = số lượng trong kho - số lượng đang chờ lấy
        query_low_stock = """
        SELECT s.tieu_de,
               (s.so_luong - COALESCE(SUM(CASE WHEN mt.trang_thai = 'Đang chờ' THEN mt.so_luong ELSE 0 END), 0)) AS so_luong_thuc_te
        FROM Sach s LEFT JOIN MuonTra mt ON s.id_sach = mt.id_sach AND mt.trang_thai = 'Đang chờ'
        WHERE s.trang_thai = 'hoat_dong'
        GROUP BY s.id_sach, s.tieu_de, s.so_luong
        HAVING so_luong_thuc_te BETWEEN 1 AND 4
        ORDER BY so_luong_thuc_te ASC LIMIT 5
        """
        cursor.execute(query_low_stock)
        low_stock_books = cursor.fetchall()

        # Lấy dữ liệu lượt mượn trong 6 tháng gần nhất cho biểu đồ
        query_chart_data = """
        SELECT DATE_FORMAT(ngay_muon, '%Y-%m') AS month, SUM(so_luong) AS total_borrows
        FROM MuonTra mt
        WHERE ngay_muon >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH) AND ngay_muon <= CURDATE()
          AND mt.trang_thai IN ('Đang mượn', 'Đã trả')
        GROUP BY month ORDER BY month ASC;
        """
        cursor.execute(query_chart_data)
        borrow_data = cursor.fetchall()

        # Chuẩn bị dữ liệu labels và values cho Chart.js
        chart_labels = [row["month"] for row in borrow_data]
        chart_values = [int(row["total_borrows"]) for row in borrow_data]

    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải dữ liệu bổ sung cho dashboard: {err}", "danger")
        (
            top_books,
            top_users,
            top_genres,
            low_stock_books,
            chart_labels,
            chart_values,
        ) = ([], [], [], [], [], [])
    finally:
        # Đóng kết nối CSDL
        cursor.close()
        conn.close()

    # Trả về template dashboard với các dữ liệu đã lấy được
    return render_template(
        "admin_dashboard.html",
        stats=stats,
        top_books=top_books,
        top_users=top_users,
        top_genres=top_genres,
        low_stock_books=low_stock_books,
        chart_labels=chart_labels,
        chart_values=chart_values,
    )


# =========================================================
# ROUTE: CÀI ĐẶT HỆ THỐNG (/admin/settings)
# =========================================================
@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def admin_settings():
    """
    Hiển thị và xử lý cập nhật các cài đặt chung của hệ thống
    (ví dụ: mức phạt, giới hạn mượn sách, thời hạn gia hạn).
    Sử dụng bảng `CaiDat` trong CSDL.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        # Xử lý khi admin submit form cài đặt
        try:
            # Lặp qua các cặp key-value trong dữ liệu form gửi lên
            for key, value in request.form.items():
                if key == "csrf_token":
                    continue  # Bỏ qua CSRF token

                # Validate giá trị: phải là số không âm
                if not value or not value.isdigit() or int(value) < 0:
                    flash(
                        f"Lỗi: Giá trị cho '{key}' phải là một số không âm.", "danger"
                    )
                    continue  # Bỏ qua cài đặt này và xử lý cài đặt tiếp theo

                # Cập nhật hoặc Thêm mới cài đặt vào CSDL
                # ON DUPLICATE KEY UPDATE: Nếu key đã tồn tại thì cập nhật value, ngược lại thì INSERT mới
                cursor.execute(
                    """
                    INSERT INTO CaiDat (setting_key, setting_value) VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE setting_value = %s
                    """,
                    (key, value, value),
                )
                ghi_nhat_ky_admin(
                    cursor, f"Đã cập nhật cài đặt: '{key}' = '{value}'"
                )  # Ghi log

            conn.commit()  # Lưu thay đổi
            flash("Cập nhật cài đặt thành công!", "success")

        except mysql.connector.Error as err:
            conn.rollback()  # Hoàn tác nếu có lỗi CSDL
            flash(f"Lỗi cơ sở dữ liệu: {err}", "danger")
        except Exception as e:
            conn.rollback()  # Hoàn tác nếu có lỗi khác
            flash(f"Đã có lỗi xảy ra: {e}", "danger")
        finally:
            # Đảm bảo đóng kết nối ngay cả khi chỉ xử lý POST
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()
        # Chuyển hướng về trang cài đặt sau khi xử lý xong
        return redirect(url_for("admin.admin_settings"))

    # Xử lý khi request là GET (hiển thị trang cài đặt)
    try:
        cursor.execute("SELECT * FROM CaiDat")  # Lấy tất cả cài đặt hiện có
        settings_list = cursor.fetchall()
        # Chuyển đổi danh sách kết quả thành dạng dict {key: value} để dễ truy cập trong template
        settings = {
            item["setting_key"]: item["setting_value"] for item in settings_list
        }
    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải cài đặt: {err}", "danger")
        settings = {}  # Trả về dict rỗng nếu có lỗi
    finally:
        # Đóng kết nối
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    # Trả về template cài đặt với dữ liệu cài đặt đã lấy
    return render_template("admin_settings.html", settings=settings)


# =========================================================
# ROUTE: QUẢN LÝ SÁCH (/admin/sach)
# =========================================================
@admin_bp.route("/sach")
@login_required
@admin_required
def quan_ly_sach():
    """
    Hiển thị trang danh sách sách cho admin.
    Hỗ trợ tìm kiếm theo tiêu đề/tác giả, lọc theo thể loại, tác giả, trạng thái.
    Có phân trang.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Lấy các tham số từ URL query string
    search_query = request.args.get("search", "")
    id_the_loai = request.args.get("id_the_loai", "")
    id_tac_gia = request.args.get("id_tac_gia", "")
    trang_thai_filter = request.args.get(
        "trang_thai", ""
    )  # Lọc theo trạng thái (hoat_dong/da_an)

    # Xử lý phân trang
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1  # Đảm bảo trang không nhỏ hơn 1
    limit = 15  # Số sách trên mỗi trang
    offset = (page - 1) * limit

    # Xây dựng mệnh đề WHERE và danh sách tham số dựa trên bộ lọc
    where_conditions = []
    params = []
    if search_query:
        where_conditions.append("(s.tieu_de LIKE %s OR tg.ten_tac_gia LIKE %s)")
        search_term = f"%{search_query}%"
        params.extend([search_term, search_term])
    if id_the_loai:
        where_conditions.append("s.id_the_loai = %s")
        params.append(id_the_loai)
    if id_tac_gia:
        where_conditions.append("s.id_tac_gia = %s")
        params.append(id_tac_gia)
    if trang_thai_filter:  # Thêm điều kiện lọc theo trạng thái
        where_conditions.append("s.trang_thai = %s")
        params.append(trang_thai_filter)

    # Kết hợp các điều kiện thành mệnh đề WHERE hoàn chỉnh
    where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""

    try:
        # Đếm tổng số sách phù hợp với bộ lọc (để tính tổng số trang)
        count_query = f"""
            SELECT COUNT(s.id_sach) AS total
            FROM Sach s LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
            LEFT JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai {where_clause}
        """
        cursor.execute(count_query, tuple(params))
        total_books = cursor.fetchone()["total"] or 0
        total_pages = math.ceil(total_books / limit) if total_books > 0 else 1

        # Lấy danh sách sách cho trang hiện tại
        query = f"""
        SELECT s.id_sach, s.tieu_de, tg.ten_tac_gia, tl.ten_the_loai,
               s.so_luong, s.trang_thai, s.anh_bia, s.so_trang, s.nam_xuat_ban
        FROM Sach s LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
        LEFT JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai {where_clause}
        ORDER BY s.id_sach DESC LIMIT %s OFFSET %s
        """
        params_paginated = params + [
            limit,
            offset,
        ]  # Thêm limit và offset vào danh sách tham số
        cursor.execute(query, tuple(params_paginated))
        danh_sach_sach = cursor.fetchall()

        # Lấy danh sách tất cả tác giả và thể loại để hiển thị trong dropdown bộ lọc
        cursor.execute(
            "SELECT id_tac_gia, ten_tac_gia FROM TacGia ORDER BY ten_tac_gia"
        )
        all_tac_gia = cursor.fetchall()
        cursor.execute(
            "SELECT id_the_loai, ten_the_loai FROM TheLoai ORDER BY ten_the_loai"
        )
        all_the_loai = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải danh sách sách: {err}", "danger")
        danh_sach_sach, all_tac_gia, all_the_loai, total_pages = [], [], [], 0
    finally:
        cursor.close()
        conn.close()

    # Trả về template quản lý sách với dữ liệu đã lấy
    return render_template(
        "admin_sach.html",
        danh_sach_sach=danh_sach_sach,
        current_page=page,
        total_pages=total_pages,
        search_query=search_query,
        all_tac_gia=all_tac_gia,
        all_the_loai=all_the_loai,
        selected_tac_gia=id_tac_gia,
        selected_the_loai=id_the_loai,
        selected_trang_thai=trang_thai_filter,
    )


# =========================================================
# ROUTE: THÊM SÁCH MỚI (/admin/sach/them)
# =========================================================
@admin_bp.route("/sach/them", methods=["GET", "POST"])
@login_required
@admin_required
def them_sach():
    """
    Hiển thị form thêm sách mới và xử lý việc thêm sách vào CSDL.
    Hỗ trợ upload ảnh bìa, tạo mới tác giả/thể loại nếu chưa có.
    Có chức năng kiểm tra trùng lặp sách (qua API /api/sach/check) và cho phép cộng dồn số lượng.
    Sử dụng AJAX để submit form và trả về JSON.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        # Xử lý khi admin submit form thêm sách (qua AJAX)
        try:
            # Lấy và chuẩn hóa dữ liệu từ form
            tieu_de_raw = request.form.get("tieu_de", "").strip()
            tieu_de = re.sub(r"\s+", " ", tieu_de_raw)
            so_luong_them = int(request.form.get("so_luong", 0))
            ten_tac_gia = request.form.get("ten_tac_gia", "").strip()
            ten_the_loai = request.form.get("ten_the_loai", "").strip()
            nam_xuat_ban = int(request.form.get("nam_xuat_ban", 0))
            so_trang_moi = int(request.form.get("so_trang", 0))
            mo_ta = request.form.get("mo_ta", "").strip()

            # Kiểm tra các trường bắt buộc
            if not all(
                [tieu_de, ten_tac_gia, ten_the_loai, nam_xuat_ban, so_luong_them > 0]
            ):
                return (
                    jsonify(
                        success=False,
                        error="Thiếu thông tin bắt buộc hoặc số lượng không hợp lệ.",
                    ),
                    400,
                )

            # Lấy ID tác giả và thể loại (tạo mới nếu chưa có)
            id_tac_gia = get_or_create(
                cursor, "TacGia", "id_tac_gia", "ten_tac_gia", ten_tac_gia
            )
            id_the_loai = get_or_create(
                cursor, "TheLoai", "id_the_loai", "ten_the_loai", ten_the_loai
            )

            # Kiểm tra sách đã tồn tại dựa trên 4 trường chính
            cursor.execute(
                """ SELECT * FROM Sach WHERE tieu_de COLLATE utf8mb4_vietnamese_ci = %s
                    AND id_tac_gia = %s AND id_the_loai = %s AND nam_xuat_ban = %s """,
                (tieu_de, id_tac_gia, id_the_loai, nam_xuat_ban),
            )
            existing_sach = cursor.fetchone()

            message = ""
            anh_bia_filename = "default_cover.jpg"  # Mặc định

            # Xử lý upload ảnh bìa (nếu có)
            if "anh_bia" in request.files:
                file = request.files["anh_bia"]
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    extension = filename.rsplit(".", 1)[1].lower()
                    anh_bia_filename = (
                        f"{uuid.uuid4().hex}.{extension}"  # Tạo tên file duy nhất
                    )
                    # Lưu file vào thư mục UPLOAD_FOLDER đã cấu hình
                    file.save(
                        os.path.join(
                            current_app.config["COVER_FOLDER"], anh_bia_filename
                        )
                    )
                    # Lưu ý: Không xóa ảnh cũ ở đây vì có thể đang cập nhật sách đã tồn tại

            if existing_sach:
                # Nếu sách đã tồn tại -> Cộng dồn số lượng và cập nhật thông tin
                new_so_luong = existing_sach["so_luong"] + so_luong_them
                # Chỉ cập nhật số trang/mô tả nếu người dùng nhập giá trị mới
                so_trang_cap_nhat = (
                    so_trang_moi
                    if so_trang_moi > 0
                    else existing_sach.get("so_trang", 0)
                )
                mo_ta_cap_nhat = mo_ta if mo_ta else existing_sach.get("mo_ta", "")
                # Nếu không upload ảnh mới, giữ lại ảnh cũ
                if not ("anh_bia" in request.files and request.files["anh_bia"]):
                    anh_bia_filename = existing_sach.get("anh_bia", "default_cover.jpg")
                else:  # Nếu có upload ảnh mới, cần xóa ảnh cũ (nếu không phải default)
                    if (
                        existing_sach.get("anh_bia")
                        and existing_sach["anh_bia"] != "default_cover.jpg"
                    ):
                        old_path = os.path.join(
                            current_app.config["COVER_FOLDER"],
                            existing_sach["anh_bia"],
                        )
                        if os.path.exists(old_path):
                            os.remove(old_path)

                # Cập nhật bản ghi sách hiện có
                cursor.execute(
                    """UPDATE Sach SET so_luong = %s, so_trang = %s, anh_bia = %s, trang_thai = 'hoat_dong', mo_ta = %s
                       WHERE id_sach = %s""",
                    (
                        new_so_luong,
                        so_trang_cap_nhat,
                        anh_bia_filename,
                        mo_ta_cap_nhat,
                        existing_sach["id_sach"],
                    ),
                )
                message = f"Sách đã tồn tại. Đã cộng thêm {so_luong_them} cuốn và cập nhật thông tin."
                ghi_nhat_ky_admin(
                    cursor, f"Đã cộng dồn {so_luong_them} cuốn vào sách '{tieu_de}'"
                )
            else:
                # Nếu sách chưa tồn tại -> Thêm mới
                # Nếu không upload ảnh, sử dụng default_cover.jpg
                if not ("anh_bia" in request.files and request.files["anh_bia"]):
                    anh_bia_filename = "default_cover.jpg"

                # Thêm bản ghi sách mới
                cursor.execute(
                    """ INSERT INTO Sach (tieu_de, id_tac_gia, id_the_loai, nam_xuat_ban, so_luong, so_trang, anh_bia, ngay_nhap, trang_thai, mo_ta)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'hoat_dong', %s) """,
                    (
                        tieu_de,
                        id_tac_gia,
                        id_the_loai,
                        nam_xuat_ban,
                        so_luong_them,
                        so_trang_moi,
                        anh_bia_filename,
                        datetime.date.today(),
                        mo_ta,
                    ),
                )
                message = "Thêm sách mới thành công!"
                ghi_nhat_ky_admin(
                    cursor, f"Đã thêm sách mới '{tieu_de}' (SL: {so_luong_them})"
                )

            conn.commit()  # Lưu thay đổi vào CSDL
            # Trả về JSON thành công
            return jsonify(
                {"success": True, "message": message, "newImage": anh_bia_filename}
            )

        except (ValueError, KeyError, mysql.connector.Error) as err:
            conn.rollback()  # Hoàn tác nếu có lỗi
            print(f"!!! Lỗi khi thêm sách: {err}")
            return (
                jsonify({"success": False, "error": f"Lỗi: {err}"}),
                500,
            )  # Trả về lỗi server
        finally:
            # Đảm bảo đóng kết nối
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    # Xử lý request GET (hiển thị form)
    try:
        # Lấy danh sách tác giả và thể loại để hiển thị trong dropdown
        cursor.execute(
            "SELECT id_tac_gia, ten_tac_gia FROM TacGia ORDER BY ten_tac_gia"
        )
        danh_sach_tac_gia = cursor.fetchall()
        cursor.execute(
            "SELECT id_the_loai, ten_the_loai FROM TheLoai ORDER BY ten_the_loai"
        )
        danh_sach_the_loai = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải danh sách tác giả/thể loại: {err}", "danger")
        danh_sach_tac_gia, danh_sach_the_loai = [], []
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    # Trả về template thêm sách
    return render_template(
        "admin_them_sach.html",
        danh_sach_tac_gia=danh_sach_tac_gia,
        danh_sach_the_loai=danh_sach_the_loai,
    )


# =========================================================
# ROUTE: SỬA THÔNG TIN SÁCH (/admin/sach/sua/<id>)
# =========================================================
@admin_bp.route("/sach/sua/<int:id_sach>", methods=["GET", "POST"])
@login_required
@admin_required
def sua_sach(id_sach):
    """
    Hiển thị form sửa thông tin sách và xử lý cập nhật.
    Hỗ trợ thay đổi ảnh bìa, tác giả, thể loại (có thể tạo mới).
    Sử dụng AJAX để submit form và trả về JSON.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        # Xử lý khi admin submit form sửa sách (qua AJAX)
        try:
            # Lấy và chuẩn hóa dữ liệu từ form
            ten_tac_gia = request.form.get("ten_tac_gia", "").strip()
            ten_the_loai = request.form.get("ten_the_loai", "").strip()
            # Lấy ID hoặc tạo mới tác giả/thể loại
            id_tac_gia = get_or_create(
                cursor, "TacGia", "id_tac_gia", "ten_tac_gia", ten_tac_gia
            )
            id_the_loai = get_or_create(
                cursor, "TheLoai", "id_the_loai", "ten_the_loai", ten_the_loai
            )

            if (
                not id_tac_gia or not id_the_loai
            ):  # Kiểm tra tác giả/thể loại có trống không
                return (
                    jsonify(
                        success=False,
                        error="Tên tác giả và thể loại không được để trống.",
                    ),
                    400,
                )

            tieu_de_raw = request.form.get("tieu_de", "").strip()
            tieu_de = re.sub(r"\s+", " ", tieu_de_raw)
            nam_xuat_ban = int(request.form.get("nam_xuat_ban", 0))
            so_luong = int(request.form.get("so_luong", 0))
            so_trang = int(request.form.get("so_trang", 0))
            mo_ta = request.form.get("mo_ta", "").strip()

            if not tieu_de or nam_xuat_ban <= 0 or so_luong < 0:
                return (
                    jsonify(
                        success=False,
                        error="Tiêu đề, năm XB (>0), số lượng (>=0) là bắt buộc.",
                    ),
                    400,
                )

            # Xử lý upload ảnh bìa mới (nếu có)
            anh_bia_filename = request.form.get(
                "anh_bia_hien_tai", "default_cover.jpg"
            )  # Lấy tên ảnh cũ từ input ẩn
            if "anh_bia" in request.files:
                file = request.files["anh_bia"]
                if file and allowed_file(file.filename):
                    # Lấy tên ảnh cũ trước khi tạo tên mới
                    old_filename = anh_bia_filename

                    # Tạo tên file duy nhất và lưu file mới
                    filename = secure_filename(file.filename)
                    extension = filename.rsplit(".", 1)[1].lower()
                    anh_bia_filename = f"{uuid.uuid4().hex}.{extension}"
                    file.save(
                        os.path.join(
                            current_app.config["COVER_FOLDER"], anh_bia_filename
                        )
                    )

                    # Xóa file ảnh cũ nếu khác default
                    if old_filename and old_filename != "default_cover.jpg":
                        old_path = os.path.join(
                            current_app.config["COVER_FOLDER"], old_filename
                        )
                        if os.path.exists(old_path):
                            os.remove(old_path)

            # Cập nhật thông tin sách trong CSDL
            cursor.execute(
                """ UPDATE Sach SET tieu_de=%s, id_tac_gia=%s, id_the_loai=%s, nam_xuat_ban=%s,
                    so_luong=%s, so_trang=%s, anh_bia=%s, mo_ta=%s WHERE id_sach=%s """,
                (
                    tieu_de,
                    id_tac_gia,
                    id_the_loai,
                    nam_xuat_ban,
                    so_luong,
                    so_trang,
                    anh_bia_filename,
                    mo_ta,
                    id_sach,
                ),
            )
            ghi_nhat_ky_admin(
                cursor, f"Đã sửa thông tin sách '{tieu_de}' (ID: {id_sach})"
            )
            conn.commit()  # Lưu thay đổi

            # Trả về JSON thành công
            return jsonify(
                {
                    "success": True,
                    "message": "Cập nhật thông tin sách thành công!",
                    "newImage": anh_bia_filename,
                }
            )

        except (ValueError, KeyError, mysql.connector.Error) as err:
            conn.rollback()
            print(f"!!! Lỗi khi sửa sách {id_sach}: {err}")
            return (
                jsonify({"success": False, "error": f"Lỗi cơ sở dữ liệu: {err}"}),
                500,
            )
        except Exception as e:
            conn.rollback()
            print(f"!!! Lỗi không xác định khi sửa sách {id_sach}: {e}")
            return jsonify({"success": False, "error": f"Lỗi không xác định: {e}"}), 500
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    # Xử lý request GET (hiển thị form sửa)
    try:
        # Lấy thông tin sách hiện tại
        query_sach = """
        SELECT s.*, tg.ten_tac_gia, tl.ten_the_loai FROM Sach s
        LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
        LEFT JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai WHERE s.id_sach = %s
        """
        cursor.execute(query_sach, (id_sach,))
        sach = cursor.fetchone()

        if not sach:
            flash("Không tìm thấy sách này.", "danger")
            return redirect(url_for("admin.quan_ly_sach"))

        # Lấy danh sách tác giả và thể loại cho dropdown
        cursor.execute(
            "SELECT id_tac_gia, ten_tac_gia FROM TacGia ORDER BY ten_tac_gia"
        )
        danh_sach_tac_gia = cursor.fetchall()
        cursor.execute(
            "SELECT id_the_loai, ten_the_loai FROM TheLoai ORDER BY ten_the_loai"
        )
        danh_sach_the_loai = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải thông tin sách để sửa: {err}", "danger")
        return redirect(url_for("admin.quan_ly_sach"))  # Chuyển hướng nếu lỗi
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    # Trả về template sửa sách với dữ liệu đã lấy
    return render_template(
        "admin_sua_sach.html",
        sach=sach,
        danh_sach_tac_gia=danh_sach_tac_gia,
        danh_sach_the_loai=danh_sach_the_loai,
    )


# =========================================================
# ROUTE: XÓA BÌNH LUẬN (/admin/binhluan/xoa/<id>)
# =========================================================
@admin_bp.route("/binhluan/xoa/<int:id_binh_luan>", methods=["POST"])
@login_required
@admin_required
def xoa_binh_luan(id_binh_luan):
    """
    Xử lý yêu cầu xóa bình luận (thường được gọi qua AJAX từ trang chi tiết sách admin).
    Trả về: JSON thông báo thành công/lỗi.
    """
    id_sach = request.form.get("id_sach_redirect")  # Lấy ID sách để redirect nếu JS lỗi
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM BinhLuan WHERE id_binh_luan = %s", (id_binh_luan,)
        )  # Xóa bình luận
        ghi_nhat_ky_admin(cursor, f"Đã xóa bình luận ID: {id_binh_luan}")  # Ghi log
        conn.commit()
        # Trả về JSON thành công
        return jsonify({"success": True, "message": "Xóa bình luận thành công"}), 200
    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        print(f"!!! DATABASE ERROR Deleting Comment {id_binh_luan}: {err}")
        return jsonify({"success": False, "error": f"Lỗi server khi xóa: {err}"}), 500
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"!!! UNEXPECTED ERROR Deleting Comment {id_binh_luan}: {e}")
        return (
            jsonify({"success": False, "error": f"Lỗi server không xác định: {e}"}),
            500,
        )
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    # Đoạn này chỉ chạy nếu return jsonify ở trên thất bại (vd: JS không xử lý được JSON)
    flash("Xóa bình luận thành công (JS Redirect Failed).", "warning")
    if id_sach:
        # Ưu tiên redirect về trang chi tiết sách nếu có ID
        return redirect(url_for("admin.admin_chi_tiet_sach", id_sach=id_sach))
    # Nếu không có ID sách, redirect về dashboard
    return redirect(url_for("admin.admin_dashboard"))


# =========================================================
# ROUTE: CHI TIẾT SÁCH (ADMIN) (/admin/sach/chitiet/<id>)
# =========================================================
@admin_bp.route("/sach/chitiet/<int:id_sach>")
@login_required
@admin_required
def admin_chi_tiet_sach(id_sach):
    """
    Hiển thị trang chi tiết sách cho admin.
    Bao gồm thông tin sách, thống kê admin (số lượng kho, đang mượn, chờ duyệt),
    lịch sử mượn của sách đó, và danh sách bình luận (có nút xóa).
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    sach = None
    stats = {}
    lich_su_muon = []
    binh_luan = []
    today_date = datetime.date.today()

    try:
        # Lấy thông tin cơ bản của sách
        query_sach = """
        SELECT s.*, tg.ten_tac_gia, tl.ten_the_loai FROM Sach s
        LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
        LEFT JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai WHERE s.id_sach = %s
        """
        cursor.execute(query_sach, (id_sach,))
        sach = cursor.fetchone()

        if not sach:
            flash("Không tìm thấy sách này.", "danger")
            return redirect(url_for("admin.quan_ly_sach"))  # Dùng tên blueprint

        # Lấy các thống kê liên quan đến sách này
        sach_trong_kho = sach.get(
            "so_luong", 0
        )  # Số lượng ghi trong bảng Sach (chưa trừ sách chờ)
        cursor.execute(
            "SELECT SUM(so_luong) as total FROM MuonTra WHERE id_sach = %s AND trang_thai = 'Đang mượn'",
            (id_sach,),
        )
        sach_dang_muon_sum = (result := cursor.fetchone()) and result.get("total") or 0
        cursor.execute(
            "SELECT COUNT(*) as total FROM MuonTra WHERE id_sach = %s AND trang_thai IN ('Đang mượn', 'Đã trả')",
            (id_sach,),
        )
        tong_luot_muon_thuc = (result := cursor.fetchone()) and result.get("total") or 0
        cursor.execute(
            "SELECT COUNT(id_muon_tra) as total FROM MuonTra WHERE id_sach = %s AND trang_thai = 'Đang chờ'",
            (id_sach,),
        )
        sach_cho_duyet_count = (
            (result := cursor.fetchone()) and result.get("total") or 0
        )  # Số lượt đặt chờ
        cursor.execute(
            "SELECT SUM(so_luong) as total FROM MuonTra WHERE id_sach = %s AND trang_thai = 'Đang chờ'",
            (id_sach,),
        )
        sach_cho_duyet_sum = (
            (result := cursor.fetchone()) and result.get("total") or 0
        )  # Tổng số cuốn đang chờ

        # Tổng số bản sao mà thư viện có = trong kho + đang mượn + đang chờ
        tong_so_ban_sao = sach_trong_kho + sach_dang_muon_sum + sach_cho_duyet_sum

        # Gom thống kê vào dict
        stats = {
            "sach_trong_kho": sach_trong_kho,
            "sach_dang_muon_sum": sach_dang_muon_sum,
            "sach_cho_duyet_count": sach_cho_duyet_count,
            "sach_cho_duyet_sum": sach_cho_duyet_sum,
            "tong_so_ban_sao": tong_so_ban_sao,
            "tong_luot_muon_thuc": tong_luot_muon_thuc,
        }

        # Lấy lịch sử mượn của sách này
        query_history = """
        SELECT tv.ho_ten, mt.ngay_muon, mt.ngay_hen_tra, mt.ngay_tra_thuc, mt.trang_thai, mt.so_luong, mt.id_thanh_vien
        FROM MuonTra mt JOIN ThanhVien tv ON mt.id_thanh_vien = tv.id_thanh_vien
        WHERE mt.id_sach = %s ORDER BY mt.ngay_muon DESC
        """
        cursor.execute(query_history, (id_sach,))
        lich_su_muon = cursor.fetchall()

        # Lấy danh sách bình luận của sách này
        query_comments = """
        SELECT bl.id_binh_luan, bl.noi_dung, bl.ngay_dang, tv.ho_ten, tv.id_thanh_vien
        FROM BinhLuan bl JOIN ThanhVien tv ON bl.id_thanh_vien = tv.id_thanh_vien
        WHERE bl.id_sach = %s ORDER BY bl.ngay_dang DESC
        """
        cursor.execute(query_comments, (id_sach,))
        binh_luan = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải chi tiết sách: {err}", "danger")
        # Gán giá trị mặc định nếu có lỗi để tránh lỗi template
        sach = sach or {}
        stats = stats or {}
        lich_su_muon = lich_su_muon or []
        binh_luan = binh_luan or []
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    # Trả về template chi tiết sách admin
    return render_template(
        "admin_chi_tiet_sach.html",
        sach=sach,
        stats=stats,
        lich_su_muon=lich_su_muon,
        binh_luan=binh_luan,
        today_date=today_date,
    )


# =========================================================
# ROUTE: ẨN SÁCH (/admin/sach/an/<id>) - AJAX
# =========================================================
@admin_bp.route("/sach/an/<int:id_sach>", methods=["POST"])
@login_required
@admin_required
def an_sach(id_sach):
    """
    Xử lý yêu cầu ẩn một cuốn sách (thay đổi trang_thai='da_an').
    Thường được gọi qua AJAX từ trang quản lý sách hoặc chi tiết sách admin.
    Trả về: JSON thông báo thành công/lỗi.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Cập nhật trạng thái sách thành 'da_an'
        cursor.execute(
            "UPDATE Sach SET trang_thai = 'da_an' WHERE id_sach = %s", (id_sach,)
        )
        ghi_nhat_ky_admin(cursor, f"Đã ẩn sách ID: {id_sach}")  # Ghi log
        conn.commit()
        return jsonify(success=True, message="Ẩn sách thành công.")  # Trả về thành công
    except mysql.connector.Error as err:
        if conn:
            conn.rollback()  # Hoàn tác nếu lỗi CSDL
        print(f"!!! Lỗi khi ẩn sách {id_sach}: {err}")
        return jsonify(success=False, error=f"Lỗi khi ẩn sách: {err}"), 500
    except Exception as e:
        if conn:
            conn.rollback()  # Hoàn tác nếu lỗi khác
        print(f"!!! Lỗi không xác định khi ẩn sách {id_sach}: {e}")
        return jsonify(success=False, error=f"Lỗi không xác định: {e}"), 500
    finally:
        # Đảm bảo đóng kết nối
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# ROUTE: KHÔI PHỤC SÁCH (/admin/sach/khoiphuc/<id>) - AJAX
# =========================================================
@admin_bp.route("/sach/khoiphuc/<int:id_sach>", methods=["POST"])
@login_required
@admin_required
def khoi_phuc_sach(id_sach):
    """
    Xử lý yêu cầu khôi phục một cuốn sách đã bị ẩn (thay đổi trang_thai='hoat_dong').
    Thường được gọi qua AJAX.
    Trả về: JSON thông báo thành công/lỗi.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Cập nhật trạng thái sách thành 'hoat_dong'
        cursor.execute(
            "UPDATE Sach SET trang_thai = 'hoat_dong' WHERE id_sach = %s", (id_sach,)
        )
        ghi_nhat_ky_admin(cursor, f"Đã khôi phục sách ID: {id_sach}")  # Ghi log
        conn.commit()
        return jsonify(
            success=True, message="Khôi phục sách thành công."
        )  # Trả về thành công
    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        print(f"!!! Lỗi khi khôi phục sách {id_sach}: {err}")
        return jsonify(success=False, error=f"Lỗi khi khôi phục sách: {err}"), 500
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"!!! Lỗi không xác định khi khôi phục sách {id_sach}: {e}")
        return jsonify(success=False, error=f"Lỗi không xác định: {e}"), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# ROUTE: QUẢN LÝ THÀNH VIÊN (/admin/thanhvien)
# =========================================================
@admin_bp.route("/thanhvien")
@login_required
@admin_required
def quan_ly_thanhvien():
    """
    Hiển thị trang danh sách thành viên cho admin.
    Hỗ trợ tìm kiếm theo tên/email, lọc theo vai trò, trạng thái.
    Có phân trang.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Lấy tham số từ URL cho phân trang và bộ lọc
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1  # Trang tối thiểu là 1
    limit = 20  # Số lượng thành viên mỗi trang
    offset = (page - 1) * limit
    search_query = request.args.get("search", "")
    selected_vai_tro = request.args.get("vai_tro", "")
    selected_trang_thai = request.args.get("trang_thai", "")

    # Xây dựng mệnh đề WHERE dựa trên bộ lọc
    where_conditions = []
    params = []
    if search_query:
        where_conditions.append(
            "(ho_ten LIKE %s OR email LIKE %s)"
        )  # Tìm kiếm tên hoặc email
        params.extend([f"%{search_query}%", f"%{search_query}%"])
    if selected_vai_tro:
        where_conditions.append("vai_tro = %s")  # Lọc theo vai trò
        params.append(selected_vai_tro)
    if selected_trang_thai:
        where_conditions.append("trang_thai = %s")  # Lọc theo trạng thái
        params.append(selected_trang_thai)
    where_clause = (
        "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
    )  # Ghép các điều kiện

    danh_sach_thanh_vien = []
    total_pages = 1
    try:
        # Đếm tổng số thành viên phù hợp
        count_query = (
            f"SELECT COUNT(id_thanh_vien) AS total FROM ThanhVien {where_clause}"
        )
        cursor.execute(count_query, tuple(params))
        total_members = cursor.fetchone()["total"] or 0
        total_pages = math.ceil(total_members / limit) if total_members > 0 else 1

        # Lấy danh sách thành viên cho trang hiện tại
        query = f""" SELECT id_thanh_vien, ho_ten, email, vai_tro, ngay_dang_ky, trang_thai
                     FROM ThanhVien {where_clause} ORDER BY id_thanh_vien LIMIT %s OFFSET %s """
        params.extend([limit, offset])  # Thêm limit và offset
        cursor.execute(query, tuple(params))
        danh_sach_thanh_vien = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải danh sách thành viên: {err}", "danger")
    finally:
        # Đóng kết nối
        cursor.close()
        conn.close()

    # Trả về template hiển thị danh sách
    return render_template(
        "admin_thanhvien.html",
        danh_sach_thanh_vien=danh_sach_thanh_vien,
        current_page=page,
        total_pages=total_pages,
        search_query=search_query,
        selected_vai_tro=selected_vai_tro,
        selected_trang_thai=selected_trang_thai,
    )


# =========================================================
# ROUTE: SỬA THÔNG TIN THÀNH VIÊN (/admin/thanhvien/sua/<id>)
# =========================================================
@admin_bp.route("/thanhvien/sua/<int:id_thanh_vien>", methods=["GET", "POST"])
@login_required
@admin_required
def sua_thanhvien(id_thanh_vien):
    """
    Hiển thị form sửa thông tin thành viên (trừ mật khẩu) và xử lý cập nhật thông tin.
    Kiểm tra email trùng lặp trước khi cập nhật.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        # Xử lý khi admin submit form sửa
        ho_ten = request.form.get("ho_ten", "").strip()
        email = request.form.get("email", "").strip()
        vai_tro = request.form.get("vai_tro", "doc_gia")
        so_dien_thoai = request.form.get("so_dien_thoai", "").strip() or None
        dia_chi = request.form.get("dia_chi", "").strip() or None
        ngay_sinh_str = request.form.get("ngay_sinh")
        ngay_sinh = None  # Mặc định là NULL
        if ngay_sinh_str:  # Chuyển đổi string thành date object nếu có
            try:
                ngay_sinh = datetime.datetime.strptime(ngay_sinh_str, "%Y-%m-%d").date()
            except ValueError:
                flash("Định dạng ngày sinh không hợp lệ.", "warning")

        if not ho_ten or not email:  # Kiểm tra trường bắt buộc
            flash("Họ tên và Email là bắt buộc.", "danger")
            return redirect(url_for("admin.sua_thanhvien", id_thanh_vien=id_thanh_vien))

        try:
            # Kiểm tra xem email mới có bị trùng với người khác không
            cursor.execute(
                "SELECT id_thanh_vien FROM ThanhVien WHERE email = %s AND id_thanh_vien != %s",
                (email, id_thanh_vien),
            )
            if cursor.fetchone():
                flash(
                    f"Lỗi: Email '{email}' đã được sử dụng bởi tài khoản khác.",
                    "danger",
                )
                return redirect(
                    url_for("admin.sua_thanhvien", id_thanh_vien=id_thanh_vien)
                )

            # Cập nhật thông tin vào CSDL
            cursor.execute(
                """ UPDATE ThanhVien SET ho_ten=%s, email=%s, vai_tro=%s, so_dien_thoai=%s, dia_chi=%s, ngay_sinh=%s
                    WHERE id_thanh_vien=%s """,
                (
                    ho_ten,
                    email,
                    vai_tro,
                    so_dien_thoai,
                    dia_chi,
                    ngay_sinh,
                    id_thanh_vien,
                ),
            )
            ghi_nhat_ky_admin(
                cursor,
                f"Đã cập nhật thông tin thành viên '{ho_ten}' (ID: {id_thanh_vien})",
            )
            conn.commit()
            flash("Cập nhật thông tin thành viên thành công!", "success")
            return redirect(url_for("admin.quan_ly_thanhvien"))  # Quay về danh sách

        except mysql.connector.Error as err:
            conn.rollback()  # Hoàn tác nếu lỗi CSDL
            flash(f"Lỗi CSDL khi cập nhật: {err}", "danger")
            print(f"!!! Lỗi DB khi sửa thành viên {id_thanh_vien}: {err}")
        except Exception as e:
            conn.rollback()  # Hoàn tác nếu lỗi khác
            flash(f"Lỗi không xác định: {e}", "danger")
            print(f"!!! Lỗi không xác định khi sửa thành viên {id_thanh_vien}: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()
        # Nếu có lỗi, quay lại trang sửa
        return redirect(url_for("admin.sua_thanhvien", id_thanh_vien=id_thanh_vien))

    # Xử lý request GET (hiển thị form)
    try:
        # Lấy thông tin thành viên hiện tại để điền vào form
        cursor.execute(
            "SELECT * FROM ThanhVien WHERE id_thanh_vien = %s", (id_thanh_vien,)
        )
        thanh_vien = cursor.fetchone()
        if not thanh_vien:  # Nếu không tìm thấy thành viên
            flash("Không tìm thấy thành viên.", "danger")
            return redirect(url_for("admin.quan_ly_thanhvien"))
    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải thông tin thành viên: {err}", "danger")
        return redirect(url_for("admin.quan_ly_thanhvien"))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    # Trả về template sửa thành viên
    return render_template("admin_sua_thanhvien.html", thanh_vien=thanh_vien)


# =========================================================
# ROUTE: KHÓA TÀI KHOẢN (/admin/thanhvien/xoa/<id>) - AJAX
# Lưu ý: Tên route là 'xoa' nhưng logic thực tế là 'khóa'
# =========================================================
@admin_bp.route("/thanhvien/xoa/<int:id_thanh_vien>", methods=["POST"])
@login_required
@admin_required
def xoa_thanhvien(id_thanh_vien):
    """
    Xử lý yêu cầu khóa tài khoản thành viên (thay đổi trang_thai='da_khoa').
    Ngăn admin tự khóa tài khoản của mình.
    Thường được gọi qua AJAX. Trả về JSON.
    """
    # Ngăn admin tự khóa tài khoản của chính mình
    if id_thanh_vien == current_user.id:
        return (
            jsonify(
                success=False, error="Bạn không thể tự khóa tài khoản của chính mình!"
            ),
            400,
        )

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Cập nhật trạng thái thành viên thành 'da_khoa'
        cursor.execute(
            "UPDATE ThanhVien SET trang_thai = 'da_khoa' WHERE id_thanh_vien = %s",
            (id_thanh_vien,),
        )
        ghi_nhat_ky_admin(cursor, f"Đã khóa thành viên ID: {id_thanh_vien}")  # Ghi log
        conn.commit()
        return jsonify(
            success=True, message="Khóa tài khoản thành công."
        )  # Trả về thành công
    except mysql.connector.Error as err:
        if conn:
            conn.rollback()  # Hoàn tác nếu lỗi CSDL
        print(f"!!! Lỗi khi khóa tài khoản {id_thanh_vien}: {err}")
        return jsonify(success=False, error=f"Lỗi khi khóa tài khoản: {err}"), 500
    except Exception as e:
        if conn:
            conn.rollback()  # Hoàn tác nếu lỗi khác
        print(f"!!! Lỗi không xác định khi khóa tài khoản {id_thanh_vien}: {e}")
        return jsonify(success=False, error=f"Lỗi không xác định: {e}"), 500
    finally:
        # Đảm bảo đóng kết nối
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# ROUTE: MỞ KHÓA TÀI KHOẢN (/admin/thanhvien/mokhoa/<id>) - AJAX
# =========================================================
@admin_bp.route("/thanhvien/mokhoa/<int:id_thanh_vien>", methods=["POST"])
@login_required
@admin_required
def mo_khoa_thanhvien(id_thanh_vien):
    """
    Xử lý yêu cầu mở khóa tài khoản thành viên (thay đổi trang_thai='hoat_dong').
    Thường được gọi qua AJAX. Trả về JSON.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Cập nhật trạng thái thành viên thành 'hoat_dong'
        cursor.execute(
            "UPDATE ThanhVien SET trang_thai = 'hoat_dong' WHERE id_thanh_vien = %s",
            (id_thanh_vien,),
        )
        ghi_nhat_ky_admin(
            cursor, f"Đã mở khóa thành viên ID: {id_thanh_vien}"
        )  # Ghi log
        conn.commit()
        return jsonify(
            success=True, message="Mở khóa tài khoản thành công."
        )  # Trả về thành công
    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        print(f"!!! Lỗi khi mở khóa tài khoản {id_thanh_vien}: {err}")
        return jsonify(success=False, error=f"Lỗi khi mở khóa tài khoản: {err}"), 500
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"!!! Lỗi không xác định khi mở khóa tài khoản {id_thanh_vien}: {e}")
        return jsonify(success=False, error=f"Lỗi không xác định: {e}"), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# ROUTE: THÊM THÀNH VIÊN MỚI (ADMIN) (/admin/thanhvien/them)
# =========================================================
@admin_bp.route("/thanhvien/them", methods=["GET", "POST"])
@login_required
@admin_required
def them_thanhvien():
    """
    Hiển thị form và xử lý việc admin thêm tài khoản thành viên mới
    (có thể là độc giả hoặc quản lý khác).
    Kiểm tra email trùng lặp. Hash mật khẩu trước khi lưu.
    """
    if request.method == "POST":
        # Xử lý khi admin submit form
        ho_ten = request.form.get("ho_ten", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password")  # Mật khẩu không strip
        vai_tro = request.form.get("vai_tro", "doc_gia")  # Mặc định là độc giả

        # --- Validation ---
        if not all([ho_ten, email, password]):
            flash("Vui lòng điền đầy đủ Họ tên, Email và Mật khẩu.", "danger")
            return redirect(url_for("admin.them_thanhvien"))
        if len(password) < 6:
            flash("Mật khẩu phải có ít nhất 6 ký tự.", "danger")
            return redirect(url_for("admin.them_thanhvien"))
        if vai_tro not in ["doc_gia", "quan_ly"]:  # Kiểm tra vai trò hợp lệ
            flash("Vai trò không hợp lệ.", "danger")
            return redirect(url_for("admin.them_thanhvien"))

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Kiểm tra email đã tồn tại chưa
            cursor.execute("SELECT email FROM ThanhVien WHERE email = %s", (email,))
            if cursor.fetchone():
                flash("Email đã được đăng ký. Vui lòng sử dụng email khác.", "danger")
                return redirect(url_for("admin.them_thanhvien"))

            # Hash mật khẩu bằng Werkzeug
            hashed_password = generate_password_hash(password)
            trang_thai = "hoat_dong"  # Trạng thái mặc định khi tạo

            # Thêm thành viên mới vào CSDL
            cursor.execute(
                "INSERT INTO ThanhVien (ho_ten, email, mat_khau, vai_tro, trang_thai) VALUES (%s, %s, %s, %s, %s)",
                (ho_ten, email, hashed_password, vai_tro, trang_thai),
            )
            ghi_nhat_ky_admin(
                cursor, f"Đã thêm thành viên mới '{ho_ten}' (Vai trò: {vai_tro})"
            )  # Ghi log
            conn.commit()  # Lưu thay đổi
            flash(f"Tài khoản '{ho_ten}' đã được tạo thành công!", "success")
            return redirect(
                url_for("admin.quan_ly_thanhvien")
            )  # Chuyển về trang danh sách

        except mysql.connector.Error as err:
            conn.rollback()  # Hoàn tác nếu lỗi CSDL
            flash(f"Lỗi khi thêm thành viên: {err}", "danger")
            print(f"!!! Lỗi DB khi admin thêm thành viên: {err}")
        except Exception as e:
            conn.rollback()  # Hoàn tác nếu lỗi khác
            flash(f"Lỗi không xác định: {e}", "danger")
            print(f"!!! Lỗi không xác định khi admin thêm thành viên: {e}")
        finally:
            cursor.close()
            conn.close()
        # Nếu có lỗi, quay lại form thêm
        return redirect(url_for("admin.them_thanhvien"))

    # Xử lý request GET (hiển thị form)
    return render_template("admin_them_thanhvien.html")


# =========================================================
# ROUTE: RESET MẬT KHẨU THÀNH VIÊN (/admin/thanhvien/reset-password/<id>) - AJAX
# =========================================================
@admin_bp.route("/thanhvien/reset-password/<int:id_thanh_vien>", methods=["POST"])
@login_required
@admin_required
def reset_matkhau(id_thanh_vien):
    """
    Xử lý yêu cầu admin đặt lại mật khẩu cho một thành viên khác (thường qua AJAX).
    Yêu cầu: POST request với 'password' trong form data.
    Trả về: JSON thông báo thành công/lỗi.
    """
    password = request.form.get("password")

    # --- Validation ---
    if not password:  # Kiểm tra mật khẩu rỗng
        return jsonify(success=False, error="Mật khẩu mới không được để trống."), 400
    if len(password) < 6:  # Kiểm tra độ dài mật khẩu
        return (
            jsonify(success=False, error="Mật khẩu mới phải có ít nhất 6 ký tự."),
            400,
        )

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Hash mật khẩu mới
        hashed_password = generate_password_hash(password)
        # Cập nhật mật khẩu trong CSDL cho thành viên tương ứng
        cursor.execute(
            "UPDATE ThanhVien SET mat_khau = %s WHERE id_thanh_vien = %s",
            (hashed_password, id_thanh_vien),
        )
        ghi_nhat_ky_admin(
            cursor, f"Đã reset mật khẩu cho thành viên ID: {id_thanh_vien}"
        )  # Ghi log
        conn.commit()  # Lưu thay đổi
        return jsonify(
            success=True, message="Đặt lại mật khẩu thành công!"
        )  # Trả về thành công
    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        print(f"!!! Lỗi DB khi reset mật khẩu cho ID {id_thanh_vien}: {err}")
        return jsonify(success=False, error=f"Lỗi khi đặt lại mật khẩu: {err}"), 500
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"!!! Lỗi không xác định khi reset mật khẩu cho ID {id_thanh_vien}: {e}")
        return jsonify(success=False, error=f"Lỗi không xác định: {e}"), 500
    finally:
        # Đảm bảo đóng kết nối
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# ROUTE: QUẢN LÝ MƯỢN/TRẢ (/admin/muontra)
# =========================================================
@admin_bp.route("/muontra")
@login_required
@admin_required
def quan_ly_muontra():
    """
    Hiển thị trang quản lý mượn/trả sách với 3 tab: Đang chờ, Đang mượn, Lịch sử.
    Hỗ trợ tìm kiếm theo ID đơn, tên sách, tên người mượn.
    Mỗi tab có phân trang riêng.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    today_date = datetime.date.today()  # Lấy ngày hiện tại để so sánh hạn trả

    # Cài đặt phân trang
    PER_PAGE = 15  # Số mục trên mỗi trang
    page_cho = request.args.get("page_cho", 1, type=int)
    page_muon = request.args.get("page_muon", 1, type=int)
    page_su = request.args.get("page_su", 1, type=int)
    # Tính offset cho từng tab
    offset_cho = (max(1, page_cho) - 1) * PER_PAGE
    offset_muon = (max(1, page_muon) - 1) * PER_PAGE
    offset_su = (max(1, page_su) - 1) * PER_PAGE

    # Xử lý tìm kiếm
    search_query = request.args.get("search", "")
    search_where_clause = ""
    search_params = []
    if search_query:
        search_term = f"%{search_query}%"
        search_conditions = [
            "s.tieu_de LIKE %s",
            "tv.ho_ten LIKE %s",
        ]  # Tìm theo tên sách hoặc tên người mượn
        search_params.extend([search_term, search_term])
        if search_query.isdigit():  # Nếu nhập số, tìm thêm theo ID đơn mượn
            search_conditions.append("mt.id_muon_tra = %s")
            search_params.append(int(search_query))
        # Tạo mệnh đề WHERE cho tìm kiếm
        search_where_clause = " AND (" + " OR ".join(search_conditions) + ")"

    # Khởi tạo các biến chứa dữ liệu và thông tin phân trang
    danh_sach_cho, danh_sach_muon, lich_su_muon = [], [], []
    total_pages_cho, total_pages_muon, total_pages_su = 1, 1, 1
    total_cho, total_muon = 0, 0

    try:
        # Phần JOIN chung cho các truy vấn lấy dữ liệu mượn trả
        base_join = """ FROM MuonTra mt JOIN Sach s ON mt.id_sach = s.id_sach JOIN ThanhVien tv ON mt.id_thanh_vien = tv.id_thanh_vien """

        # --- Lấy dữ liệu cho Tab "Đang chờ" ---
        # Đếm tổng số lượt đang chờ
        query_count_cho = f"SELECT COUNT(mt.id_muon_tra) AS total {base_join} WHERE mt.trang_thai = 'Đang chờ' {search_where_clause}"
        cursor.execute(query_count_cho, tuple(search_params))
        total_cho = cursor.fetchone()["total"] or 0
        total_pages_cho = math.ceil(total_cho / PER_PAGE) if total_cho > 0 else 1
        # Lấy danh sách lượt đang chờ cho trang hiện tại
        query_dang_cho = f""" SELECT mt.id_muon_tra, s.tieu_de, tv.ho_ten, mt.ngay_muon, mt.ngay_hen_tra, mt.so_luong {base_join}
                             WHERE mt.trang_thai = 'Đang chờ' {search_where_clause} ORDER BY mt.ngay_muon ASC LIMIT %s OFFSET %s """
        cursor.execute(query_dang_cho, tuple(search_params + [PER_PAGE, offset_cho]))
        danh_sach_cho = cursor.fetchall()

        # --- Lấy dữ liệu cho Tab "Đang mượn" ---
        # Đếm tổng số lượt đang mượn
        query_count_muon = f"SELECT COUNT(mt.id_muon_tra) AS total {base_join} WHERE mt.trang_thai = 'Đang mượn' {search_where_clause}"
        cursor.execute(query_count_muon, tuple(search_params))
        total_muon = cursor.fetchone()["total"] or 0
        total_pages_muon = math.ceil(total_muon / PER_PAGE) if total_muon > 0 else 1
        # Lấy danh sách lượt đang mượn cho trang hiện tại
        query_dang_muon = f""" SELECT mt.id_muon_tra, s.tieu_de, tv.ho_ten, mt.ngay_muon, mt.ngay_hen_tra, mt.so_luong {base_join}
                              WHERE mt.trang_thai = 'Đang mượn' {search_where_clause} ORDER BY mt.ngay_hen_tra ASC LIMIT %s OFFSET %s """
        cursor.execute(query_dang_muon, tuple(search_params + [PER_PAGE, offset_muon]))
        danh_sach_muon = cursor.fetchall()

        # --- Lấy dữ liệu cho Tab "Lịch sử" ---
        # Đếm tổng số lượt đã trả/hủy
        query_count_su = f"SELECT COUNT(mt.id_muon_tra) AS total {base_join} WHERE mt.trang_thai IN ('Đã trả', 'Đã hủy') {search_where_clause}"
        cursor.execute(query_count_su, tuple(search_params))
        total_su = cursor.fetchone()["total"] or 0
        total_pages_su = math.ceil(total_su / PER_PAGE) if total_su > 0 else 1
        # Lấy danh sách lịch sử cho trang hiện tại
        query_lich_su = f""" SELECT mt.id_muon_tra, s.tieu_de, tv.ho_ten, mt.ngay_muon, mt.ngay_tra_thuc, mt.trang_thai, mt.tien_phat, mt.so_luong {base_join}
                             WHERE mt.trang_thai IN ('Đã trả', 'Đã hủy') {search_where_clause} ORDER BY mt.ngay_tra_thuc DESC, mt.ngay_muon DESC LIMIT %s OFFSET %s """
        cursor.execute(query_lich_su, tuple(search_params + [PER_PAGE, offset_su]))
        lich_su_muon = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Lỗi cơ sở dữ liệu khi tải trang mượn trả: {err}", "danger")
        # Gán giá trị mặc định nếu có lỗi
        danh_sach_cho, danh_sach_muon, lich_su_muon = [], [], []
        total_pages_cho, total_pages_muon, total_pages_su = 1, 1, 1
        total_cho, total_muon = 0, 0

    finally:
        # Đóng kết nối CSDL
        cursor.close()
        conn.close()

    # Trả về template với tất cả dữ liệu đã lấy
    return render_template(
        "admin_muontra.html",
        today_date=today_date,
        # Dữ liệu tab chờ
        danh_sach_cho=danh_sach_cho,
        current_page_cho=page_cho,
        total_pages_cho=total_pages_cho,
        total_cho=total_cho,
        # Dữ liệu tab mượn
        danh_sach_muon=danh_sach_muon,
        current_page_muon=page_muon,
        total_pages_muon=total_pages_muon,
        total_muon=total_muon,
        # Dữ liệu tab lịch sử
        lich_su_muon=lich_su_muon,
        current_page_su=page_su,
        total_pages_su=total_pages_su,
        # Dữ liệu tìm kiếm
        search_query=search_query,
    )


# =========================================================
# ROUTE: GHI NHẬN MƯỢN SÁCH (THỦ CÔNG) (/admin/muontra/muon)
# =========================================================
@admin_bp.route("/muontra/muon", methods=["GET", "POST"])
@login_required
@admin_required
def muon_sach():
    """
    Hiển thị form và xử lý việc admin ghi nhận một lượt mượn sách thủ công.
    Admin chọn thành viên, sách, nhập số lượng, ngày mượn, ngày hẹn trả.
    Trạng thái lượt mượn sẽ là 'Đang mượn' ngay lập tức và số lượng sách bị trừ đi.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        # Xử lý khi admin submit form
        try:
            # Lấy và kiểm tra dữ liệu từ form
            id_thanh_vien = request.form["id_thanh_vien"]
            id_sach = request.form["id_sach"]
            so_luong_muon = int(request.form["so_luong_muon"])
            ngay_muon_str = request.form["ngay_muon"]
            ngay_hen_tra_str = request.form["ngay_hen_tra"]
            ngay_muon = datetime.datetime.strptime(ngay_muon_str, "%Y-%m-%d").date()
            ngay_hen_tra = datetime.datetime.strptime(
                ngay_hen_tra_str, "%Y-%m-%d"
            ).date()

            # --- Validation ---
            if so_luong_muon <= 0:
                raise ValueError("Số lượng mượn phải lớn hơn 0.")
            if ngay_hen_tra <= ngay_muon:
                raise ValueError("Ngày hẹn trả phải sau ngày mượn.")

            conn.start_transaction()  # Bắt đầu transaction

            # Khóa sách để kiểm tra và trừ số lượng
            cursor.execute(
                "SELECT so_luong, trang_thai FROM Sach WHERE id_sach = %s FOR UPDATE",
                (id_sach,),
            )
            sach = cursor.fetchone()
            # Kiểm tra sách có tồn tại, hoạt động và đủ số lượng không
            if not sach or sach.get("trang_thai") == "da_an":
                raise ValueError("Sách không có sẵn hoặc đã bị ẩn.")
            if so_luong_muon > sach.get("so_luong", 0):
                raise ValueError(
                    f"Số lượng sách trong kho không đủ (còn {sach.get('so_luong', 0)})."
                )

            # Thêm bản ghi vào bảng MuonTra với trạng thái 'Đang mượn'
            cursor.execute(
                """ INSERT INTO MuonTra (id_sach, id_thanh_vien, ngay_muon, ngay_hen_tra, so_luong, trang_thai)
                    VALUES (%s, %s, %s, %s, %s, 'Đang mượn') """,
                (id_sach, id_thanh_vien, ngay_muon, ngay_hen_tra, so_luong_muon),
            )
            # Trừ số lượng sách trong bảng Sach
            cursor.execute(
                "UPDATE Sach SET so_luong = so_luong - %s WHERE id_sach = %s",
                (so_luong_muon, id_sach),
            )
            ghi_nhat_ky_admin(
                cursor,
                f"Đã cho mượn sách ID: {id_sach} (SL: {so_luong_muon}) cho user ID: {id_thanh_vien}",
            )
            conn.commit()  # Lưu thay đổi

            flash("Ghi nhận mượn sách thành công!", "success")
            # Chuyển hướng về trang quản lý, focus tab 'Đang mượn'
            return redirect(url_for("admin.quan_ly_muontra", focus_tab="dang-muon"))

        except (ValueError, KeyError) as ve:  # Lỗi validation hoặc thiếu key
            if conn and conn.in_transaction:
                conn.rollback()
            flash(f"Dữ liệu không hợp lệ: {ve}", "danger")
        except mysql.connector.Error as err:  # Lỗi CSDL
            if conn and conn.in_transaction:
                conn.rollback()
            if "FOREIGN KEY constraint fails" in str(
                err
            ):  # Lỗi khóa ngoại (vd: thành viên không tồn tại/bị khóa)
                flash(
                    "Lỗi: Không thể cho mượn. Thành viên này có thể đã bị khóa hoặc không tồn tại.",
                    "danger",
                )
            else:
                flash(f"Lỗi cơ sở dữ liệu: {err}", "danger")
            print(f"!!! Lỗi DB khi admin ghi nhận mượn: {err}")
        except Exception as e:  # Lỗi khác
            if conn and conn.in_transaction:
                conn.rollback()
            flash(f"Lỗi không xác định: {e}", "danger")
            print(f"!!! Lỗi không xác định khi admin ghi nhận mượn: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()
        # Nếu có lỗi, quay lại form mượn sách
        return redirect(url_for("admin.muon_sach"))

    # Xử lý request GET (hiển thị form)
    try:
        # Lấy danh sách thành viên (đang hoạt động) cho dropdown
        cursor.execute(
            "SELECT id_thanh_vien, ho_ten FROM ThanhVien WHERE trang_thai = 'hoat_dong' ORDER BY ho_ten"
        )
        danh_sach_thanh_vien = cursor.fetchall()
        # Lấy danh sách sách (còn hàng và đang hoạt động) cho dropdown
        cursor.execute(
            "SELECT id_sach, tieu_de, so_luong FROM Sach WHERE so_luong > 0 AND trang_thai = 'hoat_dong' ORDER BY tieu_de"
        )
        danh_sach_sach = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải dữ liệu cho form mượn sách: {err}", "danger")
        danh_sach_thanh_vien, danh_sach_sach = [], []
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    # Trả về template form mượn sách
    return render_template(
        "admin_muon_sach.html",
        danh_sach_thanh_vien=danh_sach_thanh_vien,
        danh_sach_sach=danh_sach_sach,
    )


# =========================================================
# ROUTE: GHI NHẬN TRẢ SÁCH (/admin/muontra/tra/<id>) - AJAX
# =========================================================
@admin_bp.route("/muontra/tra/<int:id_muon_tra>", methods=["POST"])
@login_required
@admin_required
def tra_sach(id_muon_tra):
    """
    Xử lý yêu cầu ghi nhận trả sách từ admin (thường qua AJAX).
    Chuyển trạng thái lượt mượn thành 'Đã trả'.
    Tính toán và ghi nhận tiền phạt nếu sách bị trả trễ dựa trên cài đặt 'muc_phat_tre_hen'.
    Hoàn trả số lượng sách về kho.
    Trả về: JSON thông báo thành công/lỗi, ngày trả thực tế, và thông tin tiền phạt.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()  # Bắt đầu transaction

        # Lấy mức phạt mỗi ngày từ bảng CaiDat
        cursor.execute(
            "SELECT setting_value FROM CaiDat WHERE setting_key = 'muc_phat_tre_hen'"
        )
        muc_phat_row = cursor.fetchone()
        try:  # Xử lý trường hợp giá trị cài đặt không hợp lệ hoặc thiếu
            muc_phat_moi_ngay = (
                float(muc_phat_row["setting_value"]) if muc_phat_row else 0.0
            )
        except (ValueError, TypeError):
            muc_phat_moi_ngay = 0.0
            print(
                f"!!! CẢNH BÁO: Giá trị 'muc_phat_tre_hen' không hợp lệ: '{muc_phat_row.get('setting_value')}'"
            )

        # Lấy thông tin lượt mượn và khóa bản ghi (FOR UPDATE)
        cursor.execute(
            "SELECT id_sach, so_luong, ngay_hen_tra FROM MuonTra WHERE id_muon_tra = %s AND trang_thai = 'Đang mượn' FOR UPDATE",
            (id_muon_tra,),
        )
        record = cursor.fetchone()

        # Kiểm tra xem lượt mượn có tồn tại và đang ở trạng thái 'Đang mượn' không
        if not record:
            conn.rollback()
            return (
                jsonify(
                    success=False,
                    error="Không tìm thấy lượt mượn này hoặc sách đã được trả!",
                ),
                404,
            )

        # Lấy thông tin cần thiết từ bản ghi
        id_sach = record["id_sach"]
        so_luong_da_muon = record["so_luong"]
        ngay_hen_tra = record["ngay_hen_tra"]

        # Xác định thời gian trả và tính tiền phạt (nếu có)
        thoi_gian_tra_thuc = datetime.datetime.now()
        ngay_tra_thuc_date = thoi_gian_tra_thuc.date()
        tien_phat = 0.0
        message = "Đã ghi nhận trả sách thành công."  # Thông báo mặc định
        if ngay_tra_thuc_date > ngay_hen_tra:  # Kiểm tra nếu trả trễ
            so_ngay_tre = (ngay_tra_thuc_date - ngay_hen_tra).days
            tien_phat = so_ngay_tre * muc_phat_moi_ngay * so_luong_da_muon
            tien_phat_formatted = "{:,.0f} VND".format(tien_phat)
            message = f"Ghi nhận trả sách thành công. Sách trễ {so_ngay_tre} ngày. Tiền phạt: {tien_phat_formatted}."

        # Cập nhật bản ghi MuonTra: trạng thái, ngày trả thực, tiền phạt
        cursor.execute(
            """ UPDATE MuonTra SET trang_thai = 'Đã trả', ngay_tra_thuc = %s, tien_phat = %s
                WHERE id_muon_tra = %s """,
            (thoi_gian_tra_thuc, tien_phat, id_muon_tra),
        )

        # Khóa sách để cộng lại số lượng (FOR UPDATE)
        cursor.execute(
            "SELECT id_sach FROM Sach WHERE id_sach = %s FOR UPDATE", (id_sach,)
        )
        cursor.fetchone()  # Phải fetch để lock có hiệu lực
        # Cộng lại số lượng sách vào kho
        cursor.execute(
            "UPDATE Sach SET so_luong = so_luong + %s WHERE id_sach = %s",
            (so_luong_da_muon, id_sach),
        )
        ghi_nhat_ky_admin(
            cursor, f"Đã xác nhận trả sách cho lượt mượn ID: {id_muon_tra}"
        )  # Ghi log
        conn.commit()  # Lưu tất cả thay đổi

        # Chuẩn bị dữ liệu trả về cho client (AJAX)
        ngay_tra_formatted = thoi_gian_tra_thuc.strftime("%d-%m-%Y %H:%M")
        tien_phat_formatted_json = "{:,.0f} VND".format(tien_phat)

        return jsonify(
            success=True,
            message=message,
            ngay_tra_thuc=ngay_tra_formatted,
            tien_phat=tien_phat_formatted_json,
            tien_phat_raw=tien_phat,
        )

    except mysql.connector.Error as err:
        if conn and conn.in_transaction:
            conn.rollback()  # Hoàn tác nếu lỗi CSDL
        print(f"!!! Lỗi DB khi trả sách {id_muon_tra}: {err}")
        return jsonify(success=False, error=f"Lỗi cơ sở dữ liệu: {err}"), 500
    except Exception as e:
        if conn and conn.in_transaction:
            conn.rollback()  # Hoàn tác nếu lỗi khác
        print(f"!!! Lỗi không xác định khi trả sách {id_muon_tra}: {e}")
        return jsonify(success=False, error=f"Lỗi không xác định: {e}"), 500
    finally:
        # Đảm bảo đóng kết nối
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# ROUTE: XEM SÁCH QUÁ HẠN (/admin/muontra/quahan)
# =========================================================
@admin_bp.route("/muontra/quahan")
@login_required
@admin_required
def sach_qua_han():
    """
    Hiển thị danh sách các lượt mượn đang có trạng thái 'Đang mượn'
    và có ngày hẹn trả trước ngày hiện tại (CURDATE()).
    Tính toán và hiển thị số ngày trễ.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    danh_sach_qua_han = []
    try:
        # Truy vấn lấy thông tin sách quá hạn và số ngày trễ
        query = """
        SELECT s.tieu_de, tv.ho_ten, tv.email, mt.ngay_muon, mt.ngay_hen_tra,
               DATEDIFF(CURDATE(), mt.ngay_hen_tra) AS so_ngay_tre -- Tính số ngày trễ
        FROM MuonTra mt
        JOIN Sach s ON mt.id_sach = s.id_sach
        JOIN ThanhVien tv ON mt.id_thanh_vien = tv.id_thanh_vien
        WHERE mt.trang_thai = 'Đang mượn' AND mt.ngay_hen_tra < CURDATE()
        ORDER BY mt.ngay_hen_tra ASC -- Sắp xếp theo ngày hẹn trả cũ nhất
        """
        cursor.execute(query)
        danh_sach_qua_han = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải danh sách sách quá hạn: {err}", "danger")
    finally:
        # Đóng kết nối
        cursor.close()
        conn.close()

    # Trả về template hiển thị danh sách
    return render_template("admin_quahan.html", danh_sach_qua_han=danh_sach_qua_han)


# =========================================================
# ROUTE: XÁC NHẬN LẤY SÁCH (/admin/muontra/xacnhan/<id>) - AJAX
# =========================================================
@admin_bp.route("/muontra/xacnhan/<int:id_muon_tra>", methods=["POST"])
@login_required
@admin_required
def xac_nhan_lay_sach(id_muon_tra):
    """
    Xử lý yêu cầu admin xác nhận độc giả đã đến lấy sách (đặt qua web).
    Chuyển trạng thái lượt mượn từ 'Đang chờ' thành 'Đang mượn'.
    Thường được gọi qua AJAX từ trang quản lý mượn/trả. Trả về JSON.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        conn.start_transaction()  # Bắt đầu transaction

        # Cập nhật trạng thái trong bảng MuonTra, chỉ khi trạng thái hiện tại là 'Đang chờ'
        cursor.execute(
            "UPDATE MuonTra SET trang_thai = 'Đang mượn' WHERE id_muon_tra = %s AND trang_thai = 'Đang chờ'",
            (id_muon_tra,),
        )

        # Kiểm tra xem có bản ghi nào được cập nhật không
        if (
            cursor.rowcount > 0
        ):  # rowcount trả về số dòng bị ảnh hưởng bởi câu lệnh UPDATE
            # Nếu có cập nhật -> thành công
            ghi_nhat_ky_admin(
                cursor, f"Đã xác nhận lấy sách cho lượt mượn ID: {id_muon_tra}"
            )  # Ghi log
            conn.commit()  # Lưu thay đổi
            return jsonify(success=True, message="Xác nhận lấy sách thành công.")
        else:
            # Nếu không có dòng nào được cập nhật (ID sai hoặc trạng thái không phải 'Đang chờ')
            conn.rollback()  # Hoàn tác transaction (dù không có thay đổi)
            return (
                jsonify(
                    success=False, error="Không tìm thấy lượt đặt hoặc đã được xử lý."
                ),
                404,
            )  # Not Found

    except mysql.connector.Error as err:
        # Xử lý lỗi CSDL
        if conn:
            conn.rollback()
        print(f"!!! Lỗi DB khi xác nhận lấy sách ID {id_muon_tra}: {err}")
        return (
            jsonify(success=False, error=f"Lỗi cơ sở dữ liệu: {err}"),
            500,
        )  # Internal Server Error
    except Exception as e:
        # Xử lý lỗi không xác định khác
        if conn:
            conn.rollback()
        print(f"!!! Lỗi không xác định khi xác nhận lấy sách ID {id_muon_tra}: {e}")
        return (
            jsonify(success=False, error=f"Lỗi không xác định: {e}"),
            500,
        )  # Internal Server Error
    finally:
        # Đảm bảo đóng kết nối
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# ROUTE: HỦY ĐƠN ĐẶT SÁCH (ADMIN) (/admin/muontra/huy/<id>)
# =========================================================
@admin_bp.route("/muontra/huy/<int:id_muon_tra>", methods=["POST"])
@login_required
@admin_required
def huy_dat_sach(id_muon_tra):
    """
    Xử lý yêu cầu admin hủy một đơn đặt sách đang ở trạng thái 'Đang chờ'.
    Chuyển trạng thái thành 'Đã hủy', ghi nhận ngày hủy (vào cột ngay_tra_thuc).
    Hoàn trả số lượng sách về kho (cộng lại vào bảng Sach).
    Thường được gọi bằng submit form truyền thống (không AJAX) từ trang quản lý mượn/trả.
    Redirect về trang quản lý mượn trả sau khi xử lý.
    """
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()  # Bắt đầu transaction

        # Lấy thông tin lượt đặt và khóa bản ghi (FOR UPDATE)
        cursor.execute(
            """ SELECT id_sach, so_luong FROM MuonTra WHERE id_muon_tra = %s
                AND trang_thai = 'Đang chờ' FOR UPDATE """,  # Bỏ id_thanh_vien nếu là admin hủy
            (id_muon_tra,),
        )
        record = cursor.fetchone()

        # Kiểm tra xem lượt đặt có hợp lệ không
        if not record:
            conn.rollback()
            # SỬA: Trả về JSON lỗi 404
            return (
                jsonify(
                    success=False,
                    error="Không tìm thấy lượt đặt này hoặc đã được xử lý.",
                ),
                404,
            )

        id_sach = record["id_sach"]
        so_luong_dat = record["so_luong"]

        cursor.execute(
            "UPDATE MuonTra SET trang_thai = 'Đã hủy', ngay_tra_thuc = %s WHERE id_muon_tra = %s",
            (datetime.datetime.now(), id_muon_tra),
        )

        cursor.execute(
            "SELECT id_sach FROM Sach WHERE id_sach = %s FOR UPDATE", (id_sach,)
        )
        cursor.fetchone()
        cursor.execute(
            "UPDATE Sach SET so_luong = so_luong + %s WHERE id_sach = %s",
            (so_luong_dat, id_sach),
        )

        ghi_nhat_ky_admin(cursor, f"Đã hủy đặt sách cho lượt mượn ID: {id_muon_tra}")
        conn.commit()
        # SỬA: Trả về JSON thành công
        return jsonify(
            success=True, message="Đã hủy đơn đặt và hoàn trả sách về kho thành công."
        )

    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        print(f"!!! Lỗi DB khi hủy đơn {id_muon_tra}: {err}")
        # SỬA: Trả về JSON lỗi 500
        return (
            jsonify(success=False, error=f"Lỗi cơ sở dữ liệu khi hủy đơn: {err}"),
            500,
        )
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"!!! Lỗi không xác định khi hủy đơn {id_muon_tra}: {e}")
        # SỬA: Trả về JSON lỗi 500
        return jsonify(success=False, error=f"Lỗi không xác định khi hủy đơn: {e}"), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
