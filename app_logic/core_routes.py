# app_logic/core_routes.py
# =========================================================
# FILE CORE ROUTES
# Chứa các route chính, công khai của ứng dụng dành cho người dùng (độc giả).
# Bao gồm trang chủ, trang danh sách sách (tra cứu), trang chi tiết sách,
# và xử lý các hành động liên quan như thêm bình luận.
# Các route này thường yêu cầu người dùng đăng nhập (@login_required).
# =========================================================

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import (
    login_required,
    current_user,
)  # Để kiểm tra đăng nhập và lấy thông tin user
from app_logic.db import get_db_connection  # Hàm lấy kết nối CSDL
from app_logic.utils import slugify  # Hàm tạo slug
import math  # Để tính toán phân trang
import datetime  # Để xử lý ngày tháng
import mysql.connector  # Để xử lý lỗi CSDL

# Tạo Blueprint cho các route cốt lõi
core_bp = Blueprint("core", __name__, template_folder="templates")


# =========================================================
# ROUTE: TRANG CHỦ ("/")
# =========================================================
@core_bp.route("/")
@login_required  # Yêu cầu người dùng phải đăng nhập để xem trang chủ
def index():
    """
    Hiển thị trang chủ.
    - Nếu không có tham số tìm kiếm/lọc: Hiển thị các danh sách sách cuộn ngang
      (Mới nhất, Phổ biến, Gợi ý).
    - Nếu có tham số tìm kiếm/lọc (search, id_the_loai, id_tac_gia):
      Hiển thị kết quả tìm kiếm/lọc dưới dạng lưới có phân trang.
    Luôn hiển thị form tìm kiếm và các dropdown lọc (Tác giả, Thể loại).
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)  # Dùng dictionary=True để kết quả là dict

    # Lấy các tham số tìm kiếm, lọc và phân trang từ URL query string
    search_query = request.args.get("search", "")
    id_the_loai = request.args.get("id_the_loai", "")
    id_tac_gia = request.args.get("id_tac_gia", "")
    search_page = request.args.get(
        "search_page", 1, type=int
    )  # Trang hiện tại của kết quả tìm kiếm
    if search_page < 1:
        search_page = 1  # Đảm bảo trang >= 1
    PER_PAGE_SEARCH = 12  # Số sách trên mỗi trang kết quả tìm kiếm
    search_offset = (search_page - 1) * PER_PAGE_SEARCH

    # Lấy danh sách thể loại và tác giả để hiển thị trong dropdown bộ lọc
    try:
        cursor.execute(
            "SELECT id_the_loai, ten_the_loai FROM TheLoai ORDER BY ten_the_loai"
        )
        danh_sach_the_loai = cursor.fetchall()
        cursor.execute(
            "SELECT id_tac_gia, ten_tac_gia FROM TacGia ORDER BY ten_tac_gia"
        )
        danh_sach_tac_gia = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải bộ lọc: {err}", "danger")
        danh_sach_the_loai, danh_sach_tac_gia = [], []

    # Xác định xem người dùng có đang thực hiện tìm kiếm/lọc không
    is_searching = bool(search_query or id_the_loai or id_tac_gia)

    # Khởi tạo các biến chứa kết quả
    search_results_paginated = []  # Kết quả tìm kiếm (nếu có)
    search_title = ""  # Tiêu đề cho mục kết quả tìm kiếm
    total_search_pages = 1  # Tổng số trang kết quả tìm kiếm
    sach_moi_nhat = []  # Danh sách sách mới nhất
    sach_goi_y = []  # Danh sách sách gợi ý
    sach_pho_bien = []  # Danh sách sách phổ biến

    try:
        if is_searching:
            # --- XỬ LÝ KHI CÓ TÌM KIẾM/LỌC ---
            search_title = "Kết quả tìm kiếm"
            # Xây dựng mệnh đề WHERE dựa trên các tham số lọc
            where_conditions = ["s.trang_thai = 'hoat_dong'"]  # Chỉ lấy sách hoạt động
            params_where = []  # Tham số cho mệnh đề WHERE
            if search_query:
                where_conditions.append("(s.tieu_de LIKE %s OR tg.ten_tac_gia LIKE %s)")
                params_where.extend([f"%{search_query}%", f"%{search_query}%"])
            if id_the_loai:
                where_conditions.append("s.id_the_loai = %s")
                params_where.append(id_the_loai)
            if id_tac_gia:
                where_conditions.append("s.id_tac_gia = %s")
                params_where.append(id_tac_gia)
            where_clause_str = (
                "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
            )

            # Đếm tổng số kết quả phù hợp để tính phân trang
            count_base_from = " FROM Sach s LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia LEFT JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai "
            count_query = (
                f"SELECT COUNT(s.id_sach) AS total {count_base_from} {where_clause_str}"
            )
            cursor.execute(count_query, tuple(params_where))
            total_search_results = cursor.fetchone()["total"] or 0
            total_search_pages = (
                math.ceil(total_search_results / PER_PAGE_SEARCH)
                if total_search_results > 0
                else 1
            )

            # Đảm bảo trang hiện tại không vượt quá tổng số trang
            if search_page > total_search_pages:
                search_page = total_search_pages
                search_offset = (search_page - 1) * PER_PAGE_SEARCH

            # Lấy danh sách sách cho trang kết quả tìm kiếm hiện tại
            select_part = " SELECT s.id_sach, s.tieu_de, s.anh_bia, tg.ten_tac_gia, (CASE WHEN yt.id_thanh_vien IS NOT NULL THEN TRUE ELSE FALSE END) AS is_favorite "
            from_joins_part = """ FROM Sach s LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia LEFT JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai
                                   LEFT JOIN YeuThich yt ON s.id_sach = yt.id_sach AND yt.id_thanh_vien = %s """
            order_limit_offset_part = " ORDER BY s.tieu_de LIMIT %s OFFSET %s "
            final_search_query = f"{select_part} {from_joins_part} {where_clause_str} {order_limit_offset_part}"
            # Tham số cuối cùng bao gồm: user_id (cho YeuThich), các tham số lọc, limit, offset
            final_params = (
                [current_user.id] + params_where + [PER_PAGE_SEARCH, search_offset]
            )
            cursor.execute(final_search_query, tuple(final_params))
            search_results_paginated = cursor.fetchall()  # Lấy kết quả

        else:
            # --- XỬ LÝ KHI KHÔNG TÌM KIẾM/LỌC (HIỂN THỊ MẶC ĐỊNH) ---
            # Lấy 10 sách mới nhất
            cursor.execute(
                """ SELECT s.id_sach, s.tieu_de, s.anh_bia, tg.ten_tac_gia, (CASE WHEN yt.id_thanh_vien IS NOT NULL THEN TRUE ELSE FALSE END) AS is_favorite
                    FROM Sach s LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia LEFT JOIN YeuThich yt ON s.id_sach = yt.id_sach AND yt.id_thanh_vien = %s
                    WHERE s.trang_thai = 'hoat_dong' ORDER BY s.id_sach DESC LIMIT 10 """,
                (current_user.id,),
            )
            sach_moi_nhat = cursor.fetchall()

            # Lấy thể loại ưa thích của người dùng (dựa trên lịch sử mượn)
            cursor.execute(
                """ SELECT s.id_the_loai, COUNT(*) AS so_luong FROM MuonTra mt JOIN Sach s ON mt.id_sach = s.id_sach
                    WHERE mt.id_thanh_vien = %s GROUP BY s.id_the_loai ORDER BY so_luong DESC LIMIT 1 """,
                (current_user.id,),
            )
            the_loai_ua_thich = cursor.fetchone()

            # Lấy sách gợi ý dựa trên thể loại ưa thích (chưa từng mượn)
            if the_loai_ua_thich:
                cursor.execute(
                    """ SELECT s.id_sach, s.tieu_de, s.anh_bia, tg.ten_tac_gia, (CASE WHEN yt.id_thanh_vien IS NOT NULL THEN TRUE ELSE FALSE END) AS is_favorite
                        FROM Sach s LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia LEFT JOIN YeuThich yt ON s.id_sach = yt.id_sach AND yt.id_thanh_vien = %s
                        WHERE s.id_the_loai = %s AND s.trang_thai = 'hoat_dong'
                          AND s.id_sach NOT IN (SELECT DISTINCT id_sach FROM MuonTra WHERE id_thanh_vien = %s)
                        LIMIT 10 """,
                    (
                        current_user.id,
                        the_loai_ua_thich["id_the_loai"],
                        current_user.id,
                    ),
                )
                sach_goi_y = cursor.fetchall()

            # Nếu không có gợi ý theo thể loại, lấy sách mượn nhiều nhất làm gợi ý
            if not sach_goi_y:
                cursor.execute(
                    """ SELECT s.id_sach, s.tieu_de, s.anh_bia, tg.ten_tac_gia, COUNT(mt.id_sach) AS luot_muon,
                           MAX(CASE WHEN yt.id_thanh_vien IS NOT NULL THEN TRUE ELSE FALSE END) AS is_favorite
                        FROM Sach s JOIN MuonTra mt ON s.id_sach = mt.id_sach LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
                           LEFT JOIN YeuThich yt ON s.id_sach = yt.id_sach AND yt.id_thanh_vien = %s
                        WHERE s.trang_thai = 'hoat_dong' GROUP BY s.id_sach, s.tieu_de, s.anh_bia, tg.ten_tac_gia
                        ORDER BY luot_muon DESC LIMIT 10 """,
                    (current_user.id,),
                )
                sach_goi_y = cursor.fetchall()  # Gán sách phổ biến vào gợi ý

            # Lấy 10 sách phổ biến nhất (mượn nhiều nhất)
            cursor.execute(
                """ SELECT s.id_sach, s.tieu_de, s.anh_bia, tg.ten_tac_gia, COUNT(mt.id_muon_tra) AS luot_muon,
                       MAX(CASE WHEN yt.id_thanh_vien IS NOT NULL THEN TRUE ELSE FALSE END) AS is_favorite
                    FROM Sach s JOIN MuonTra mt ON s.id_sach = mt.id_sach LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
                       LEFT JOIN YeuThich yt ON s.id_sach = yt.id_sach AND yt.id_thanh_vien = %s
                    WHERE s.trang_thai = 'hoat_dong' GROUP BY s.id_sach, s.tieu_de, s.anh_bia, tg.ten_tac_gia
                    ORDER BY luot_muon DESC LIMIT 10 """,
                (current_user.id,),
            )
            sach_pho_bien = cursor.fetchall()

    except mysql.connector.Error as err:
        flash(f"Lỗi cơ sở dữ liệu khi tải trang chủ: {err}", "danger")
        # Gán danh sách rỗng nếu có lỗi
        search_results_paginated, sach_moi_nhat, sach_goi_y, sach_pho_bien = (
            [],
            [],
            [],
            [],
        )
    finally:
        # Đóng kết nối CSDL
        cursor.close()
        conn.close()

    # Trả về template home.html với các dữ liệu đã lấy được
    return render_template(
        "home.html",
        # Dữ liệu cho bộ lọc
        danh_sach_the_loai=danh_sach_the_loai,
        danh_sach_tac_gia=danh_sach_tac_gia,
        # Trạng thái tìm kiếm và các giá trị lọc đã chọn
        is_searching=is_searching,
        selected_the_loai=id_the_loai,
        selected_tac_gia=id_tac_gia,
        search_query=search_query,
        # Dữ liệu kết quả tìm kiếm và phân trang (nếu có)
        search_title=search_title,
        search_results_paginated=search_results_paginated,
        current_search_page=search_page,
        total_search_pages=total_search_pages,
        # Dữ liệu cho các danh sách mặc định
        sach_moi_nhat=sach_moi_nhat,
        sach_goi_y=sach_goi_y,
        sach_pho_bien=sach_pho_bien,
    )


# =========================================================
# ROUTE: CHI TIẾT SÁCH ("/sach/<id>" hoặc "/sach/<id>/<slug>")
# =========================================================
@core_bp.route("/sach/<int:id_sach>")  # Route không có slug
@core_bp.route("/sach/<int:id_sach>/<path:slug>")  # Route có slug (để URL đẹp hơn)
@login_required  # Yêu cầu đăng nhập
def chi_tiet_sach(id_sach, slug=None):
    """
    Hiển thị trang chi tiết của một cuốn sách.
    Bao gồm thông tin sách, tác giả, thể loại, số lượng, mô tả, lượt mượn,
    đánh giá trung bình, đánh giá của người dùng hiện tại (nếu có),
    danh sách bình luận, và danh sách sách liên quan (cùng tác giả/thể loại).
    Kiểm tra slug và redirect nếu slug không đúng hoặc thiếu để đảm bảo URL chuẩn.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Lấy thông tin chi tiết sách, bao gồm cả trạng thái yêu thích của người dùng hiện tại
        query_sach = """
        SELECT s.*, tg.ten_tac_gia, tl.ten_the_loai, (CASE WHEN yt.id_thanh_vien IS NOT NULL THEN TRUE ELSE FALSE END) AS is_favorite
        FROM Sach s LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia LEFT JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai
           LEFT JOIN YeuThich yt ON s.id_sach = yt.id_sach AND yt.id_thanh_vien = %s
        WHERE s.id_sach = %s AND s.trang_thai = 'hoat_dong' -- Chỉ lấy sách hoạt động
        """
        cursor.execute(query_sach, (current_user.id, id_sach))
        sach = cursor.fetchone()

        # Nếu không tìm thấy sách hoặc sách đã bị ẩn
        if not sach:
            flash("Sách này không tồn tại hoặc đã bị ẩn.", "danger")
            return redirect(url_for("core.danh_sach_sach"))  # Chuyển về trang danh sách

        # --- Kiểm tra và Redirect nếu Slug không đúng ---
        expected_slug = slugify(sach.get("tieu_de"))  # Tạo slug chuẩn từ tiêu đề sách
        if slug is None or slug != expected_slug:  # Nếu slug bị thiếu hoặc sai
            # Redirect vĩnh viễn (301) đến URL đúng với slug chuẩn
            return redirect(
                url_for("core.chi_tiet_sach", id_sach=id_sach, slug=expected_slug),
                code=301,
            )

        # Lấy tổng lượt mượn của sách này
        cursor.execute(
            "SELECT COUNT(*) as total FROM MuonTra WHERE id_sach = %s", (id_sach,)
        )
        luot_muon = cursor.fetchone()["total"] or 0

        # Lấy danh sách bình luận (mới nhất trước)
        query_comments = """ SELECT bl.noi_dung, bl.ngay_dang, tv.ho_ten FROM BinhLuan bl JOIN ThanhVien tv ON bl.id_thanh_vien = tv.id_thanh_vien
                             WHERE bl.id_sach = %s ORDER BY bl.ngay_dang DESC """
        cursor.execute(query_comments, (id_sach,))
        binh_luan = cursor.fetchall()

        # Lấy danh sách sách liên quan (cùng tác giả hoặc thể loại, trừ sách hiện tại, ngẫu nhiên)
        query_related = """ SELECT s.id_sach, s.tieu_de, s.anh_bia, tg.ten_tac_gia, (CASE WHEN yt.id_thanh_vien IS NOT NULL THEN TRUE ELSE FALSE END) AS is_favorite
                            FROM Sach s LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia LEFT JOIN YeuThich yt ON s.id_sach = yt.id_sach AND yt.id_thanh_vien = %s
                            WHERE (s.id_tac_gia = %s OR s.id_the_loai = %s) AND s.id_sach != %s AND s.trang_thai = 'hoat_dong'
                            ORDER BY RAND() LIMIT 10 """  # RAND() để lấy ngẫu nhiên
        # Lấy ID tác giả/thể loại của sách hiện tại, dùng -1 nếu không có để tránh lỗi SQL
        id_tac_gia = sach.get("id_tac_gia") or -1
        id_the_loai = sach.get("id_the_loai") or -1
        cursor.execute(
            query_related, (current_user.id, id_tac_gia, id_the_loai, id_sach)
        )
        sach_lien_quan = cursor.fetchall()

        # Tính điểm đánh giá trung bình
        avg_rating = 0
        tong_diem = sach.get("tong_diem", 0) or 0  # Dùng or 0 để đảm bảo là số
        so_luot = sach.get("so_luot_danh_gia", 0) or 0
        if so_luot > 0:
            avg_rating = round(tong_diem / so_luot, 1)  # Làm tròn 1 chữ số thập phân

        # Lấy đánh giá của người dùng hiện tại cho sách này (nếu có)
        user_rating = 0  # Mặc định là chưa đánh giá
        cursor.execute(
            "SELECT diem_so FROM DanhGia WHERE id_sach = %s AND id_thanh_vien = %s",
            (id_sach, current_user.id),
        )
        rating_record = cursor.fetchone()
        if rating_record:
            user_rating = rating_record["diem_so"]

    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải chi tiết sách: {err}", "danger")
        print(f"!!! Lỗi DB khi xem chi tiết sách {id_sach}: {err}")
        return redirect(url_for("core.danh_sach_sach"))  # Chuyển hướng nếu lỗi
    finally:
        # Đóng kết nối
        cursor.close()
        conn.close()

    # Trả về template chi tiết sách với các dữ liệu đã lấy
    return render_template(
        "chi_tiet_sach.html",
        sach=sach,
        luot_muon=luot_muon,
        binh_luan=binh_luan,
        sach_lien_quan=sach_lien_quan,
        avg_rating=avg_rating,
        user_rating=user_rating,
    )


# =========================================================
# ROUTE: DANH SÁCH SÁCH (TRA CỨU) ("/sach")
# =========================================================
@core_bp.route("/sach")
@login_required  # Yêu cầu đăng nhập
def danh_sach_sach():
    """
    Hiển thị trang tra cứu sách dưới dạng lưới (grid).
    Hỗ trợ tìm kiếm, lọc theo thể loại/tác giả, lọc sách còn hàng,
    sắp xếp theo tiêu đề/năm XB (tăng/giảm).
    Có phân trang.
    """
    # Lấy các tham số từ URL query string
    search_query = request.args.get("search", "")
    id_the_loai = request.args.get("id_the_loai", "")
    id_tac_gia = request.args.get("id_tac_gia", "")
    sort_by = request.args.get("sort_by", "tieu_de")  # Mặc định sắp xếp theo tiêu đề
    sort_order = request.args.get("sort_order", "asc")  # Mặc định tăng dần
    # Chuyển đổi 'available_only=true' thành boolean True
    available_only = request.args.get(
        "available_only", type=lambda v: v.lower() == "true"
    )
    page = request.args.get("page", 1, type=int)  # Trang hiện tại
    per_page = 12  # Số sách mỗi trang

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Xây dựng mệnh đề WHERE và danh sách tham số dựa trên bộ lọc
    where_conditions = ["s.trang_thai = 'hoat_dong'"]  # Luôn chỉ lấy sách hoạt động
    filter_params = []  # Danh sách tham số cho câu lệnh SQL
    if available_only:
        where_conditions.append("s.so_luong > 0")  # Lọc sách còn hàng
    if search_query:
        where_conditions.append(
            "(s.tieu_de LIKE %s OR tg.ten_tac_gia LIKE %s)"
        )  # Tìm kiếm
        search_term = f"%{search_query}%"
        filter_params.extend([search_term, search_term])
    if id_the_loai:
        where_conditions.append("s.id_the_loai = %s")  # Lọc theo thể loại
        filter_params.append(id_the_loai)
    if id_tac_gia:
        where_conditions.append("s.id_tac_gia = %s")  # Lọc theo tác giả
        filter_params.append(id_tac_gia)
    # Kết hợp các điều kiện
    where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""

    total_sach = 0
    total_pages = 1
    try:
        # Đếm tổng số sách phù hợp với bộ lọc
        count_query = f""" SELECT COUNT(s.id_sach) AS total FROM Sach s
                           LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
                           LEFT JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai {where_clause} """
        cursor.execute(count_query, tuple(filter_params))
        result = cursor.fetchone()
        if result:
            total_sach = result["total"] or 0
        # Tính tổng số trang
        total_pages = math.ceil(total_sach / per_page) if total_sach > 0 else 1
    except mysql.connector.Error as err:
        flash(f"Lỗi khi đếm sách: {err}", "danger")
        print(f"!!! SQL Error (Count): {err}")

    # Điều chỉnh trang hiện tại nếu vượt quá tổng số trang hoặc nhỏ hơn 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page  # Tính offset cho LIMIT

    # Xây dựng phần SELECT và JOIN của câu lệnh chính
    select_fields = """ SELECT s.id_sach, s.tieu_de, tg.ten_tac_gia, tl.ten_the_loai, s.so_luong, s.anh_bia, s.nam_xuat_ban,
                           (CASE WHEN yt.id_thanh_vien IS NOT NULL THEN TRUE ELSE FALSE END) AS is_favorite """
    from_join_part = """ FROM Sach s LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
                         LEFT JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai
                         LEFT JOIN YeuThich yt ON s.id_sach = yt.id_sach AND yt.id_thanh_vien = %s """

    # Xây dựng mệnh đề ORDER BY dựa trên tham số sắp xếp
    order_by_clause = "ORDER BY "
    if sort_by == "nam_xb":
        order_by_clause += "s.nam_xuat_ban"
    else:  # Mặc định sắp xếp theo tiêu đề (có hỗ trợ tiếng Việt)
        order_by_clause += "s.tieu_de COLLATE utf8mb4_vietnamese_ci"
    order_by_clause += " DESC" if sort_order == "desc" else " ASC"  # Thứ tự tăng/giảm

    # Mệnh đề LIMIT và OFFSET
    limit_offset_clause = " LIMIT %s OFFSET %s"

    # Gộp tất cả các phần thành câu lệnh SQL cuối cùng
    final_query = f"{select_fields} {from_join_part} {where_clause} {order_by_clause} {limit_offset_clause}"
    # Chuẩn bị danh sách tham số cuối cùng (user_id cho JOIN YeuThich, các tham số lọc, limit, offset)
    main_query_params = [current_user.id] + filter_params + [per_page, offset]

    danh_sach = []
    try:
        # Thực thi câu lệnh lấy danh sách sách cho trang hiện tại
        cursor.execute(final_query, tuple(main_query_params))
        danh_sach = cursor.fetchall()  # Lấy kết quả
    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải danh sách sách: {err}", "danger")
        print(f"!!! SQL Error (Select): {err}")

    # Lấy danh sách thể loại và tác giả để hiển thị trong bộ lọc
    danh_sach_the_loai = []
    danh_sach_tac_gia = []
    try:
        cursor.execute(
            "SELECT id_the_loai, ten_the_loai FROM TheLoai ORDER BY ten_the_loai"
        )
        danh_sach_the_loai = cursor.fetchall()
        cursor.execute(
            "SELECT id_tac_gia, ten_tac_gia FROM TacGia ORDER BY ten_tac_gia"
        )
        danh_sach_tac_gia = cursor.fetchall()
    except mysql.connector.Error as err:
        flash(f"Lỗi khi tải danh sách bộ lọc: {err}", "danger")
        print(f"!!! SQL Error (Filters): {err}")
    finally:
        # Đóng kết nối CSDL
        cursor.close()
        conn.close()

    # Trả về template sach.html với các dữ liệu đã lấy
    return render_template(
        "sach.html",
        danh_sach=danh_sach,  # Danh sách sách cho trang hiện tại
        # Thông tin phân trang
        current_page=page,
        total_pages=total_pages,
        # Các giá trị lọc/tìm kiếm/sắp xếp hiện tại (để giữ trạng thái form)
        search_query=search_query,
        danh_sach_the_loai=danh_sach_the_loai,
        danh_sach_tac_gia=danh_sach_tac_gia,
        selected_the_loai=id_the_loai,
        selected_tac_gia=id_tac_gia,
        sort_by=sort_by,
        sort_order=sort_order,
        available_only=available_only,
    )


# =========================================================
# ROUTE: THÊM BÌNH LUẬN ("/sach/<id>/comment") - AJAX
# =========================================================
@core_bp.route("/sach/<int:id_sach>/comment", methods=["POST"])
@login_required  # Yêu cầu đăng nhập để bình luận
def them_binh_luan(id_sach):
    """
    Xử lý yêu cầu thêm bình luận mới cho một cuốn sách (gửi qua AJAX).
    Yêu cầu: POST request với 'noi_dung' trong form data.
    Trả về: JSON chứa thông tin bình luận mới (nếu thành công) hoặc lỗi.
    """
    noi_dung = request.form.get("noi_dung")  # Lấy nội dung bình luận từ form
    # Validation: kiểm tra bình luận không được rỗng
    if not noi_dung or not noi_dung.strip():
        return (
            jsonify(success=False, error="Bình luận không được để trống."),
            400,
        )  # Bad Request

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        noi_dung_sach = noi_dung.strip()  # Loại bỏ khoảng trắng thừa
        thoi_gian_dang = datetime.datetime.now()  # Lấy thời gian hiện tại

        # Thêm bình luận vào CSDL
        cursor.execute(
            "INSERT INTO BinhLuan (id_sach, id_thanh_vien, noi_dung, ngay_dang) VALUES (%s, %s, %s, %s)",
            (id_sach, current_user.id, noi_dung_sach, thoi_gian_dang),
        )
        conn.commit()  # Lưu thay đổi

        # Trả về JSON thành công cùng thông tin bình luận mới để JavaScript cập nhật UI
        return jsonify(
            success=True,
            message="Gửi bình luận thành công!",
            user_name=current_user.ho_ten,  # Tên người bình luận
            comment_date=thoi_gian_dang.strftime("%d-%m-%Y"),  # Định dạng ngày
            comment_content=noi_dung_sach,  # Nội dung bình luận
        )

    except mysql.connector.Error as err:
        if conn:
            conn.rollback()  # Hoàn tác nếu lỗi CSDL
        error_msg = f"Lỗi cơ sở dữ liệu: {err}"
        # Kiểm tra lỗi khóa ngoại (sách hoặc user không tồn tại)
        if "FOREIGN KEY constraint fails" in str(err):
            error_msg = "Lỗi: Không thể bình luận do sách hoặc tài khoản không hợp lệ."
        print(f"!!! Lỗi DB khi thêm bình luận sách {id_sach}: {err}")
        return jsonify(success=False, error=error_msg), 500  # Internal Server Error
    except Exception as e:
        if conn:
            conn.rollback()  # Hoàn tác nếu lỗi khác
        print(f"!!! Lỗi không xác định khi thêm bình luận: {e}")
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
