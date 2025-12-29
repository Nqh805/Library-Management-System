# app_logic/api_routes.py
# =========================================================
# FILE API ROUTES
# Chứa các endpoint API được sử dụng bởi JavaScript (Fetch API/AJAX)
# để thực hiện các hành động không đồng bộ và trả về dữ liệu JSON.
# Các API này giúp tăng tính tương tác và phản hồi của ứng dụng
# mà không cần tải lại toàn bộ trang.
# =========================================================

import mysql.connector
import re
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

# Import các hàm/lớp cần thiết từ các module khác
from app_logic.db import get_db_connection
from app_logic.utils import (
    slugify,
    admin_required,
)  # Import hàm slugify và decorator admin_required

# Tạo Blueprint cho API với tiền tố /api
# Tất cả các route trong file này sẽ có dạng /api/...
api_bp = Blueprint("api", __name__, url_prefix="/api")


# =========================================================
# API: THÊM/BỎ YÊU THÍCH SÁCH
# =========================================================
@api_bp.route("/sach/toggle-favorite/<int:id_sach>", methods=["POST"])
@login_required  # Yêu cầu người dùng đăng nhập
def toggle_favorite(id_sach):
    """
    API endpoint để thêm hoặc xóa một cuốn sách khỏi danh sách yêu thích của người dùng.
    Yêu cầu: POST request, người dùng phải đăng nhập và là độc giả.
    Trả về: JSON thông báo thành công/lỗi và trạng thái yêu thích mới (is_favorite: true/false).
    """
    # Chỉ độc giả mới được yêu thích
    if current_user.vai_tro != "doc_gia":
        return (
            jsonify(success=False, error="Chỉ độc giả mới có thể yêu thích sách."),
            403,
        )

    conn = None
    cursor = None
    try:
        # Kết nối CSDL và bắt đầu transaction
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()

        # 1. Kiểm tra sách tồn tại và hoạt động
        cursor.execute(
            "SELECT id_sach FROM Sach WHERE id_sach = %s AND trang_thai = 'hoat_dong'",
            (id_sach,),
        )
        sach = cursor.fetchone()
        if not sach:
            conn.rollback()
            return (
                jsonify(success=False, error="Sách không tồn tại hoặc đã bị ẩn."),
                404,
            )

        # 2. Kiểm tra trạng thái yêu thích hiện tại (dùng FOR UPDATE để khóa dòng, tránh race condition)
        cursor.execute(
            "SELECT id_yeu_thich FROM YeuThich WHERE id_thanh_vien = %s AND id_sach = %s FOR UPDATE",
            (current_user.id, id_sach),
        )
        existing_favorite = cursor.fetchone()

        if existing_favorite:
            # 3a. Nếu đã thích -> Bỏ thích (DELETE)
            cursor.execute(
                "DELETE FROM YeuThich WHERE id_yeu_thich = %s",
                (existing_favorite["id_yeu_thich"],),
            )
            conn.commit()
            return jsonify(success=True, message="Đã bỏ yêu thích", is_favorite=False)
        else:
            # 3b. Nếu chưa thích -> Thêm vào yêu thích (INSERT)
            cursor.execute(
                "INSERT INTO YeuThich (id_thanh_vien, id_sach) VALUES (%s, %s)",
                (current_user.id, id_sach),
            )
            conn.commit()
            return jsonify(
                success=True, message="Đã thêm vào yêu thích", is_favorite=True
            )

    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        if err.errno == 1062:  # Xử lý lỗi trùng lặp (vd: click nhanh 2 lần)
            return jsonify(success=False, error="Yêu cầu đang được xử lý."), 409
        print(f"!!! Lỗi DB khi toggle favorite: {err}")
        return jsonify(success=False, error=f"Lỗi cơ sở dữ liệu: {err}"), 500
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"!!! Lỗi không xác định khi toggle favorite: {e}")
        return jsonify(success=False, error=f"Lỗi không xác định: {e}"), 500
    finally:
        # Đảm bảo đóng kết nối
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# API: LẤY CHI TIẾT SÁCH THEO TIÊU ĐỀ (CHO ADMIN)
# =========================================================
@api_bp.route("/sach/<tieu_de>")
@login_required
@admin_required  # Yêu cầu quyền admin
def get_sach_details_by_title(tieu_de):
    """
    API endpoint (chủ yếu cho admin) để lấy chi tiết sách dựa trên tiêu đề chính xác.
    Trả về: JSON chứa thông tin sách hoặc lỗi 404.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Lấy thông tin cơ bản của sách dựa trên tiêu đề
        query = """
        SELECT s.tieu_de, tg.ten_tac_gia, tl.ten_the_loai
        FROM Sach s
        JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
        JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai
        WHERE s.tieu_de = %s
        LIMIT 1
        """
        cursor.execute(query, (tieu_de,))
        sach = cursor.fetchone()
        if sach:
            return jsonify(sach)  # Trả về thông tin sách
        else:
            return jsonify({"error": "Not found"}), 404  # Không tìm thấy
    except mysql.connector.Error as err:
        print(f"Lỗi API get_sach_details: {err}")
        return jsonify({"error": "Lỗi máy chủ"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# API: KIỂM TRA SÁCH TỒN TẠI (CHO ADMIN THÊM SÁCH)
# =========================================================
@api_bp.route("/sach/check")
@login_required
@admin_required  # Yêu cầu quyền admin
def check_sach_exists():
    """
    API endpoint cho trang "Thêm sách" của admin để kiểm tra xem sách
    (dựa trên Tiêu đề, Tác giả, Thể loại, Năm XB) đã tồn tại trong CSDL chưa.
    Sử dụng bởi JavaScript để cảnh báo admin và chuyển sang chế độ cộng dồn/cập nhật.
    Trả về: JSON {"found": true/false, "details": {...}} hoặc {"found": false, "reason": "..."}.
    """
    # Lấy và chuẩn hóa dữ liệu đầu vào từ query string
    tieu_de_raw = request.args.get("tieu_de", "").strip()
    tieu_de = re.sub(r"\s+", " ", tieu_de_raw)  # Loại bỏ khoảng trắng thừa
    ten_tac_gia = request.args.get("ten_tac_gia", "").strip()
    ten_the_loai = request.args.get("ten_the_loai", "").strip()
    nam_xuat_ban_str = request.args.get("nam_xuat_ban", "").strip()

    # Kiểm tra thiếu thông tin
    if not all([tieu_de, ten_tac_gia, ten_the_loai, nam_xuat_ban_str]):
        return jsonify({"found": False, "reason": "Chưa đủ thông tin"})
    try:
        nam_xuat_ban = int(nam_xuat_ban_str)  # Kiểm tra năm hợp lệ
    except ValueError:
        return jsonify({"found": False, "reason": "Năm không hợp lệ"})

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # Lấy ID tác giả và thể loại (nếu có)
        cursor.execute(
            "SELECT id_tac_gia FROM TacGia WHERE ten_tac_gia = %s", (ten_tac_gia,)
        )
        tac_gia_row = cursor.fetchone()
        cursor.execute(
            "SELECT id_the_loai FROM TheLoai WHERE ten_the_loai = %s", (ten_the_loai,)
        )
        the_loai_row = cursor.fetchone()

        # Nếu tác giả hoặc thể loại chưa có -> sách chắc chắn mới
        if not tac_gia_row or not the_loai_row:
            return jsonify({"found": False, "reason": "Tác giả hoặc thể loại mới"})

        id_tac_gia = tac_gia_row["id_tac_gia"]
        id_the_loai = the_loai_row["id_the_loai"]

        # Truy vấn kiểm tra sách dựa trên 4 trường chính
        query = """
        SELECT s.tieu_de, tg.ten_tac_gia, tl.ten_the_loai, s.nam_xuat_ban, s.so_trang
        FROM Sach s
        JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
        JOIN TheLoai tl ON s.id_the_loai = tl.id_the_loai
        WHERE s.tieu_de COLLATE utf8mb4_vietnamese_ci = %s -- So sánh không phân biệt hoa/thường/dấu
          AND s.id_tac_gia = %s
          AND s.id_the_loai = %s
          AND s.nam_xuat_ban = %s
        LIMIT 1
        """
        cursor.execute(query, (tieu_de, id_tac_gia, id_the_loai, nam_xuat_ban))
        sach = cursor.fetchone()

        if sach:
            # Sách đã tồn tại
            return jsonify({"found": True, "details": sach})
        else:
            # Sách chưa tồn tại
            return jsonify({"found": False, "reason": "Không tìm thấy sách trùng khớp"})

    except mysql.connector.Error as err:
        print(f"!!! Lỗi DB khi check sách tồn tại: {err}")
        return jsonify({"error": str(err)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# API: TÌM KIẾM SÁCH NHANH (LIVE SEARCH)
# =========================================================
@api_bp.route("/live-search-sach")
@login_required  # Yêu cầu đăng nhập
def live_search_sach():
    """
    API endpoint cho chức năng tìm kiếm sách nhanh (live search).
    Lấy từ khóa 'q' từ query string.
    Trả về: JSON là một danh sách các sách phù hợp (tối đa 7), bao gồm slug, tên tác giả, lượt mượn.
    """
    search_query = request.args.get("q", "")  # Lấy từ khóa

    # Chỉ tìm khi từ khóa đủ dài
    if len(search_query) < 2:
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    search_term = f"%{search_query}%"  # Chuẩn bị cho LIKE
    try:
        # Câu lệnh SQL tìm kiếm và sắp xếp
        query = """
            SELECT
                s.id_sach, s.tieu_de, s.anh_bia, tg.ten_tac_gia,
                COUNT(mt.id_muon_tra) AS luot_muon
            FROM Sach s
            LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
            LEFT JOIN MuonTra mt ON s.id_sach = mt.id_sach
            WHERE
                (LOWER(s.tieu_de) LIKE LOWER(%s) OR LOWER(tg.ten_tac_gia) LIKE LOWER(%s))
                AND s.trang_thai = 'hoat_dong'
            GROUP BY s.id_sach, s.tieu_de, s.anh_bia, tg.ten_tac_gia
            ORDER BY luot_muon DESC, s.tieu_de ASC
            LIMIT 7
        """
        cursor.execute(query, (search_term, search_term))
        results = cursor.fetchall()

        # Xử lý kết quả: thêm slug, xử lý tác giả NULL
        processed_results = []
        for sach in results:
            sach["slug"] = slugify(sach["tieu_de"])  # Tạo slug
            sach["ten_tac_gia"] = sach.get("ten_tac_gia", "N/A")  # Xử lý NULL
            processed_results.append(sach)

        return jsonify(processed_results)  # Trả về kết quả

    except mysql.connector.Error as err:
        print(f"Lỗi API Live Search: {err}")
        return jsonify({"error": "Lỗi máy chủ"}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# API: ĐÁNH GIÁ SÁCH (1-5 SAO)
# =========================================================
@api_bp.route("/sach/<int:id_sach>/rate", methods=["POST"])
@login_required
def rate_sach(id_sach):
    """
    API endpoint để người dùng (độc giả) gửi hoặc cập nhật đánh giá (1-5 sao) cho một cuốn sách.
    Yêu cầu: POST request với 'rating' trong form data.
    Trả về: JSON thông báo thành công/lỗi, điểm trung bình mới (avg_rating) và tổng số lượt đánh giá mới (rating_count).
    """
    # Chỉ độc giả được đánh giá
    if current_user.vai_tro != "doc_gia":
        return (
            jsonify(success=False, error="Chỉ độc giả mới có thể đánh giá sách."),
            403,
        )

    # Validate điểm đánh giá (phải là số 1-5)
    try:
        rating_value = int(request.form.get("rating"))
        if not (1 <= rating_value <= 5):
            raise ValueError("Điểm đánh giá không hợp lệ.")
    except (ValueError, TypeError):
        return jsonify(success=False, error="Điểm đánh giá phải là số từ 1 đến 5."), 400

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()  # Bắt đầu transaction

        # 1. Khóa sách để đọc/cập nhật điểm, kiểm tra sách tồn tại
        cursor.execute(
            "SELECT id_sach, tong_diem, so_luot_danh_gia FROM Sach WHERE id_sach = %s AND trang_thai = 'hoat_dong' FOR UPDATE",
            (id_sach,),
        )
        sach = cursor.fetchone()
        if not sach:
            conn.rollback()
            return (
                jsonify(success=False, error="Sách không tồn tại hoặc đã bị ẩn."),
                404,
            )

        # 2. Khóa đánh giá cũ của user (nếu có)
        cursor.execute(
            "SELECT id_danh_gia, diem_so FROM DanhGia WHERE id_sach = %s AND id_thanh_vien = %s FOR UPDATE",
            (id_sach, current_user.id),
        )
        old_rating_record = cursor.fetchone()
        old_rating_value = 0
        is_update = bool(old_rating_record)  # Kiểm tra xem có phải cập nhật không
        if is_update:
            old_rating_value = old_rating_record["diem_so"]

        # 3. Lấy điểm và số lượt hiện tại của sách
        current_tong_diem = sach.get("tong_diem", 0) or 0
        current_so_luot = sach.get("so_luot_danh_gia", 0) or 0

        # 4. Xử lý cập nhật hoặc thêm mới đánh giá
        if is_update:
            # 4a. Cập nhật đánh giá cũ
            if rating_value == old_rating_value:  # Không thay đổi
                conn.rollback()
                avg_rating_no_change = (
                    round(current_tong_diem / current_so_luot, 1)
                    if current_so_luot > 0
                    else 0
                )
                return jsonify(
                    success=True,
                    message="Đánh giá không thay đổi.",
                    avg_rating=avg_rating_no_change,
                    rating_count=current_so_luot,
                )

            # Cập nhật điểm trong bảng DanhGia
            cursor.execute(
                "UPDATE DanhGia SET diem_so = %s, ngay_danh_gia = CURRENT_TIMESTAMP WHERE id_danh_gia = %s",
                (rating_value, old_rating_record["id_danh_gia"]),
            )
            # Tính lại tổng điểm (dựa trên chênh lệch)
            delta_diem = rating_value - old_rating_value
            new_tong_diem = current_tong_diem + delta_diem
            new_so_luot_danh_gia = current_so_luot  # Số lượt không đổi
        else:
            # 4b. Thêm đánh giá mới
            cursor.execute(
                "INSERT INTO DanhGia (id_sach, id_thanh_vien, diem_so) VALUES (%s, %s, %s)",
                (id_sach, current_user.id, rating_value),
            )
            # Tính lại tổng điểm và số lượt
            new_tong_diem = current_tong_diem + rating_value
            new_so_luot_danh_gia = current_so_luot + 1

        # 5. Cập nhật lại tổng điểm và số lượt trong bảng Sach
        cursor.execute(
            "UPDATE Sach SET tong_diem = %s, so_luot_danh_gia = %s WHERE id_sach = %s",
            (new_tong_diem, new_so_luot_danh_gia, id_sach),
        )

        conn.commit()  # Lưu thay đổi

        # 6. Tính điểm trung bình mới
        new_avg_rating = (
            round(new_tong_diem / new_so_luot_danh_gia, 1)
            if new_so_luot_danh_gia > 0
            else 0
        )

        # 7. Trả về kết quả
        return jsonify(
            success=True,
            message="Cảm ơn bạn đã đánh giá!",
            avg_rating=new_avg_rating,
            rating_count=new_so_luot_danh_gia,
        )

    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        # Xử lý các lỗi DB cụ thể
        if err.errno == 1062:
            return jsonify(success=False, error="Lỗi trùng lặp đánh giá."), 409
        if "chk_diem_so_range" in str(err):
            return jsonify(success=False, error="Điểm đánh giá phải từ 1 đến 5."), 400
        print(f"!!! Lỗi DB khi đánh giá sách {id_sach}: {err}")
        return jsonify(success=False, error=f"Lỗi cơ sở dữ liệu: {err}"), 500
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"!!! Lỗi không xác định khi đánh giá sách {id_sach}: {e}")
        return jsonify(success=False, error=f"Lỗi không xác định: {e}"), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
