# app_logic/profile_routes.py
# =========================================================
# FILE PROFILE ROUTES
# Chứa các route liên quan đến hồ sơ cá nhân và các hành động
# của người dùng đã đăng nhập (cả Độc giả và Quản lý).
# Bao gồm xem thông tin, cập nhật thông tin, đổi mật khẩu,
# quản lý sách đang mượn/lịch sử/yêu thích (đối với độc giả),
# xem nhật ký hoạt động (đối với quản lý).
# Tất cả các route trong file này đều có tiền tố /profile (ngoại trừ /muon-sach/<id>).
# =========================================================

import os  # Module thao tác với hệ điều hành (vd: xóa file avatar cũ)
import uuid  # Module tạo ID duy nhất (cho tên file avatar)
import datetime  # Module xử lý ngày tháng
import mysql.connector  # Module kết nối CSDL MySQL
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    current_app,  # Import current_app để truy cập config của ứng dụng
)
from flask_login import (
    login_required,
    current_user,
)  # Để kiểm tra đăng nhập và lấy thông tin user
from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)  # Để hash/kiểm tra mật khẩu
from werkzeug.utils import secure_filename  # Để làm sạch tên file upload

# Nhập các hàm/lớp cần thiết từ các module khác
from app_logic.db import get_db_connection  # Hàm lấy kết nối CSDL
from app_logic.utils import allowed_file  # Hàm kiểm tra đuôi file avatar

# Tạo Blueprint cho các route liên quan đến hồ sơ người dùng
# Tiền tố /profile sẽ tự động được thêm vào các route định nghĩa trong blueprint này
# (trừ khi route được định nghĩa với '/' - xem route profile() dưới đây)
profile_bp = Blueprint(
    "profile", __name__, template_folder="templates"
)  # Không đặt url_prefix ở đây


# =========================================================
# ROUTE: TRANG HỒ SƠ CÁ NHÂN ("/profile")
# =========================================================
@profile_bp.route("/profile")  # Đường dẫn là /profile
@login_required  # Yêu cầu người dùng phải đăng nhập
def profile():
    """
    Hiển thị trang hồ sơ cá nhân của người dùng đang đăng nhập.
    Lấy thông tin cá nhân, và tùy theo vai trò (độc giả/quản lý),
    lấy thêm danh sách sách đang mượn, lịch sử mượn, sách yêu thích,
    hoặc nhật ký hoạt động của admin.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)  # Sử dụng dictionary=True để kết quả là dict

    try:
        # Lấy thông tin cơ bản của người dùng hiện tại từ CSDL
        cursor.execute(
            "SELECT ho_ten, email, ngay_dang_ky, ngay_sinh, so_dien_thoai, dia_chi, avatar FROM ThanhVien WHERE id_thanh_vien = %s",
            (current_user.id,),
        )
        user_info = cursor.fetchone()

        # Nếu không tìm thấy thông tin (trường hợp hiếm gặp), báo lỗi và chuyển hướng
        if not user_info:
            flash("Không tìm thấy thông tin người dùng.", "danger")
            return redirect(url_for("core.index"))  # Chuyển về trang chủ

        # Khởi tạo các danh sách dữ liệu sẽ lấy (tùy theo vai trò)
        sach_dang_muon = []
        lich_su_muon = []
        sach_yeu_thich = []
        nhat_ky_hoat_dong = []
        today_date = datetime.date.today()  # Lấy ngày hiện tại để so sánh hạn trả

        # Kiểm tra vai trò của người dùng để lấy dữ liệu tương ứng
        if current_user.vai_tro == "doc_gia":
            # --- Lấy dữ liệu cho Độc giả ---
            # Lấy danh sách sách đang mượn hoặc đang chờ duyệt
            cursor.execute(
                """ SELECT s.tieu_de, mt.ngay_muon, mt.ngay_hen_tra, mt.so_luong, mt.trang_thai, mt.id_muon_tra
                    FROM MuonTra mt JOIN Sach s ON mt.id_sach = s.id_sach
                    WHERE mt.id_thanh_vien = %s AND mt.trang_thai IN ('Đang mượn', 'Đang chờ')
                    ORDER BY mt.ngay_muon DESC """,  # Sắp xếp theo ngày mượn/đặt gần nhất
                (current_user.id,),
            )
            sach_dang_muon = cursor.fetchall()

            # Lấy lịch sử các sách đã trả (giới hạn 20 lượt gần nhất)
            cursor.execute(
                """ SELECT s.tieu_de, mt.ngay_muon, mt.ngay_tra_thuc, mt.trang_thai, mt.tien_phat
                    FROM MuonTra mt JOIN Sach s ON mt.id_sach = s.id_sach
                    WHERE mt.id_thanh_vien = %s AND mt.trang_thai = 'Đã trả'
                    ORDER BY mt.ngay_tra_thuc DESC LIMIT 20 """,  # Sắp xếp theo ngày trả gần nhất
                (current_user.id,),
            )
            lich_su_muon = cursor.fetchall()

            # Lấy danh sách các sách yêu thích (đang hoạt động)
            cursor.execute(
                """ SELECT s.id_sach, s.tieu_de, s.anh_bia, tg.ten_tac_gia, s.so_luong
                    FROM YeuThich yt JOIN Sach s ON yt.id_sach = s.id_sach LEFT JOIN TacGia tg ON s.id_tac_gia = tg.id_tac_gia
                    WHERE yt.id_thanh_vien = %s AND s.trang_thai = 'hoat_dong'
                    ORDER BY yt.ngay_them DESC """,  # Sắp xếp theo ngày thêm gần nhất
                (current_user.id,),
            )
            sach_yeu_thich = cursor.fetchall()

        elif current_user.vai_tro == "quan_ly":
            # --- Lấy dữ liệu cho Quản lý ---
            # Lấy 20 hoạt động gần nhất của admin này từ AdminLog
            cursor.execute(
                """ SELECT hanh_dong, thoi_gian FROM AdminLog WHERE id_admin = %s
                    ORDER BY thoi_gian DESC LIMIT 20 """,
                (current_user.id,),
            )
            nhat_ky_hoat_dong = cursor.fetchall()

    except mysql.connector.Error as err:
        # Xử lý lỗi nếu không lấy được dữ liệu từ CSDL
        flash(f"Lỗi khi tải dữ liệu hồ sơ: {err}", "danger")
        print(f"!!! Lỗi DB khi tải trang profile cho user {current_user.id}: {err}")
        # Gán giá trị mặc định để tránh lỗi template
        user_info = user_info or {}  # Giữ lại user_info nếu đã lấy được
        sach_dang_muon, lich_su_muon, sach_yeu_thich, nhat_ky_hoat_dong = [], [], [], []
    finally:
        # Đảm bảo đóng kết nối CSDL
        cursor.close()
        conn.close()

    # Trả về template profile.html với các dữ liệu đã thu thập
    return render_template(
        "profile.html",
        user_info=user_info,  # Thông tin cơ bản
        sach_dang_muon=sach_dang_muon,  # Danh sách sách đang mượn/chờ
        lich_su_muon=lich_su_muon,  # Lịch sử mượn
        sach_yeu_thich=sach_yeu_thich,  # Sách yêu thích
        today_date=today_date,  # Ngày hiện tại (để so sánh hạn trả)
        vai_tro=current_user.vai_tro,  # Vai trò (để hiển thị tab phù hợp)
        nhat_ky_hoat_dong=nhat_ky_hoat_dong,  # Nhật ký admin (nếu là admin)
    )


# =========================================================
# ROUTE: CẬP NHẬT THÔNG TIN HỒ SƠ ("/profile/update") - Form Submit
# =========================================================
@profile_bp.route("/profile/update", methods=["POST"])
@login_required  # Yêu cầu đăng nhập
def update_profile():
    """
    Xử lý yêu cầu cập nhật thông tin hồ sơ người dùng (gửi từ modal).
    Bao gồm cập nhật thông tin cá nhân (tên, sđt, địa chỉ, ngày sinh)
    và xử lý upload ảnh đại diện (avatar) mới.
    Sử dụng submit form truyền thống (không AJAX). Redirect về trang profile sau khi xử lý.
    """
    conn = get_db_connection()
    # Không dùng dictionary=True vì chỉ thực hiện UPDATE
    cursor = conn.cursor()
    try:
        # Lấy dữ liệu từ form gửi lên
        ho_ten = request.form.get("ho_ten", "").strip()
        so_dien_thoai = (
            request.form.get("so_dien_thoai", "").strip() or None
        )  # Lưu NULL nếu rỗng
        dia_chi = request.form.get("dia_chi", "").strip() or None
        ngay_sinh_str = request.form.get("ngay_sinh")

        # Chuyển đổi chuỗi ngày sinh thành đối tượng date (nếu có và hợp lệ)
        ngay_sinh = None
        if ngay_sinh_str:
            try:
                ngay_sinh = datetime.datetime.strptime(ngay_sinh_str, "%Y-%m-%d").date()
            except ValueError:
                # Báo lỗi nhẹ nếu định dạng sai, nhưng vẫn tiếp tục cập nhật các thông tin khác
                flash(
                    "Định dạng ngày sinh không hợp lệ, ngày sinh không được cập nhật.",
                    "warning",
                )

        # --- Xử lý upload file avatar mới ---
        avatar_filename = (
            current_user.avatar
        )  # Giữ lại tên file avatar hiện tại làm mặc định

        if (
            "avatar" in request.files
        ):  # Kiểm tra xem có trường 'avatar' trong request.files không
            file = request.files["avatar"]  # Lấy đối tượng file
            # Kiểm tra file có tồn tại, có tên và có đuôi file hợp lệ không
            if file and file.filename != "" and allowed_file(file.filename):
                # Làm sạch tên file để tránh các ký tự đặc biệt hoặc đường dẫn nguy hiểm
                filename = secure_filename(file.filename)
                # Lấy đuôi file (vd: 'jpg', 'png')
                extension = filename.rsplit(".", 1)[1].lower()
                # Tạo tên file duy nhất bằng UUID để tránh trùng lặp và khó đoán tên file
                unique_filename = f"{uuid.uuid4().hex}.{extension}"

                # Xác định đường dẫn đầy đủ để lưu file mới trong thư mục UPLOAD_FOLDER
                save_path = os.path.join(
                    current_app.config["AVATAR_FOLDER"], unique_filename
                )
                try:
                    file.save(save_path)  # Lưu file mới vào thư mục static
                except Exception as save_error:
                    # Bắt lỗi nếu không lưu được file (vd: quyền ghi, hết dung lượng)
                    flash(f"Lỗi khi lưu ảnh đại diện: {save_error}", "danger")
                    raise  # Ném lại lỗi để transaction được rollback

                # --- Xóa file avatar cũ (nếu có và không phải là ảnh mặc định) ---
                if current_user.avatar and current_user.avatar != "default_avatar.png":
                    old_path = os.path.join(
                        current_app.config["AVATAR_FOLDER"], current_user.avatar
                    )
                    if os.path.exists(old_path):  # Kiểm tra file cũ tồn tại
                        try:
                            os.remove(old_path)  # Xóa file cũ
                        except OSError as remove_error:
                            # Báo lỗi nếu không xóa được file cũ nhưng vẫn tiếp tục
                            print(
                                f"!!! CẢNH BÁO: Không thể xóa avatar cũ '{current_user.avatar}': {remove_error}"
                            )
                            flash(f"Không thể xóa ảnh đại diện cũ.", "warning")

                avatar_filename = unique_filename  # Cập nhật tên file mới để lưu vào DB
            # Nếu người dùng chọn file nhưng loại file không hợp lệ
            elif file and file.filename != "":
                flash(
                    f"Loại file ảnh không hợp lệ. Chỉ chấp nhận: {', '.join(current_app.config.get('ALLOWED_EXTENSIONS',[]))}",
                    "warning",
                )
                # Không thay đổi avatar_filename, giữ lại ảnh cũ trong DB

        # --- Cập nhật thông tin vào CSDL ---
        # Cập nhật các trường thông tin cá nhân và tên file avatar mới (hoặc cũ)
        cursor.execute(
            """ UPDATE ThanhVien SET ho_ten = %s, so_dien_thoai = %s, dia_chi = %s, ngay_sinh = %s, avatar = %s
                WHERE id_thanh_vien = %s """,
            (
                ho_ten,
                so_dien_thoai,
                dia_chi,
                ngay_sinh,
                avatar_filename,
                current_user.id,
            ),
        )
        conn.commit()  # Lưu thay đổi vào CSDL
        flash("Cập nhật hồ sơ thành công!", "success")  # Thông báo thành công

    except Exception as e:
        # Xử lý lỗi chung (bao gồm lỗi lưu file đã raise ở trên hoặc lỗi CSDL)
        if conn:
            conn.rollback()  # Hoàn tác tất cả thay đổi trong transaction nếu có lỗi
        flash(f"Lỗi khi cập nhật hồ sơ: {e}", "danger")  # Thông báo lỗi
        print(
            f"!!! Lỗi khi cập nhật profile user {current_user.id}: {e}"
        )  # Ghi log lỗi
    finally:
        # Đảm bảo đóng kết nối CSDL
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    # Chuyển hướng người dùng về trang profile sau khi xử lý xong (dù thành công hay lỗi)
    return redirect(
        url_for("profile.profile")
    )  # Sử dụng tên blueprint "profile" và tên hàm "profile"


# =========================================================
# ROUTE: CẬP NHẬT MẬT KHẨU ("/profile/update-password") - AJAX
# =========================================================
@profile_bp.route("/profile/update-password", methods=["POST"])
@login_required  # Yêu cầu đăng nhập
def update_password():
    """
    Xử lý yêu cầu thay đổi mật khẩu người dùng (gửi từ modal qua AJAX).
    Kiểm tra mật khẩu cũ, mật khẩu mới khớp và đủ độ dài.
    Hash mật khẩu mới và cập nhật vào CSDL.
    Trả về: JSON thông báo thành công hoặc lỗi (với mã HTTP tương ứng).
    """
    conn = None
    cursor = None
    try:
        # Lấy dữ liệu mật khẩu từ form gửi lên (AJAX)
        old_password = request.form.get("old_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        # --- Validation phía server ---
        if not all(
            [old_password, new_password, confirm_password]
        ):  # Kiểm tra thiếu trường
            return (
                jsonify(success=False, error="Vui lòng điền đầy đủ tất cả các trường."),
                400,
            )
        if new_password != confirm_password:  # Kiểm tra khớp mật khẩu mới
            return (
                jsonify(
                    success=False, error="Mật khẩu mới và xác nhận mật khẩu không khớp."
                ),
                400,
            )
        if len(new_password) < 6:  # Kiểm tra độ dài mật khẩu mới
            return (
                jsonify(success=False, error="Mật khẩu mới phải có ít nhất 6 ký tự."),
                400,
            )

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Lấy mật khẩu hash hiện tại từ CSDL để so sánh
        cursor.execute(
            "SELECT mat_khau FROM ThanhVien WHERE id_thanh_vien = %s",
            (current_user.id,),
        )
        user_data = cursor.fetchone()

        if not user_data:  # Không tìm thấy user (hiếm gặp)
            return jsonify(success=False, error="Không tìm thấy người dùng."), 404

        # Kiểm tra mật khẩu cũ có đúng không
        if not check_password_hash(user_data["mat_khau"], old_password):
            return jsonify(success=False, error="Mật khẩu cũ không chính xác."), 400

        # Hash mật khẩu mới bằng Werkzeug
        new_hashed_password = generate_password_hash(new_password)

        # Cập nhật mật khẩu mới (đã hash) vào CSDL
        cursor.execute(
            "UPDATE ThanhVien SET mat_khau = %s WHERE id_thanh_vien = %s",
            (new_hashed_password, current_user.id),
        )
        conn.commit()  # Lưu thay đổi

        # Trả về JSON thông báo thành công
        return jsonify(success=True, message="Cập nhật mật khẩu thành công!")

    except mysql.connector.Error as err:
        # Xử lý lỗi CSDL
        if conn:
            conn.rollback()
        print(f"!!! Lỗi DB khi cập nhật mật khẩu user {current_user.id}: {err}")
        return jsonify(success=False, error=f"Lỗi cơ sở dữ liệu: {err}"), 500
    except Exception as e:
        # Xử lý lỗi không xác định khác
        if conn:
            conn.rollback()
        print(
            f"!!! Lỗi không xác định khi cập nhật mật khẩu user {current_user.id}: {e}"
        )
        return jsonify(success=False, error=f"Lỗi không xác định: {e}"), 500
    finally:
        # Đảm bảo đóng kết nối CSDL
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# ROUTE: ĐỘC GIẢ ĐẶT LỊCH MƯỢN SÁCH ("/muon-sach/<id>") - AJAX
# Lưu ý: Route này không nằm trong /profile prefix nhưng logic liên quan đến người dùng
#        và được gọi từ trang chi tiết sách hoặc trang tra cứu sách.
# =========================================================
@profile_bp.route(
    "/muon-sach/<int:id_sach>", methods=["POST"]
)  # Không có prefix /profile
@login_required  # Yêu cầu đăng nhập
def user_muon_sach(id_sach):
    """
    Xử lý yêu cầu độc giả đặt lịch mượn sách (gửi từ modal qua AJAX).
    Kiểm tra giới hạn mượn, số lượng sách còn lại, ngày hợp lệ.
    Tạo bản ghi mới trong MuonTra với trạng thái 'Đang chờ'.
    Trừ số lượng sách trong bảng Sach (số lượng tạm giữ).
    Trả về: JSON thông báo thành công hoặc lỗi.
    """
    # Chỉ cho phép độc giả thực hiện chức năng này
    if current_user.vai_tro == "quan_ly":
        return jsonify(success=False, error="Chức năng này chỉ dành cho độc giả."), 403

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()  # Bắt đầu transaction

        # Lấy và kiểm tra dữ liệu từ form (gửi qua AJAX)
        so_luong_muon = int(request.form["so_luong_muon"])
        ngay_lay_sach_str = request.form["ngay_lay_sach"]
        ngay_tra_sach_str = request.form["ngay_tra_sach"]
        ngay_lay = datetime.datetime.strptime(ngay_lay_sach_str, "%Y-%m-%d").date()
        ngay_tra = datetime.datetime.strptime(ngay_tra_sach_str, "%Y-%m-%d").date()

        # --- Validation phía server ---
        if so_luong_muon <= 0:
            raise ValueError("Số lượng mượn phải lớn hơn 0.")
        if ngay_lay < datetime.date.today():
            raise ValueError("Ngày lấy sách không được là ngày trong quá khứ.")
        if ngay_tra <= ngay_lay:
            raise ValueError("Ngày trả sách phải sau ngày lấy sách.")

        # --- Kiểm tra giới hạn mượn sách ---
        # Lấy giới hạn từ cài đặt
        cursor.execute(
            "SELECT setting_value FROM CaiDat WHERE setting_key = 'max_sach_muon_moi_user'"
        )
        limit_row = cursor.fetchone()
        max_limit = (
            int(limit_row["setting_value"])
            if limit_row and limit_row.get("setting_value", "").isdigit()
            else 5
        )
        # Đếm số sách đang mượn + chờ (khóa để đảm bảo tính đúng đắn)
        cursor.execute(
            "SELECT SUM(so_luong) AS total FROM MuonTra WHERE id_thanh_vien = %s AND trang_thai IN ('Đang mượn', 'Đang chờ') FOR UPDATE",
            (current_user.id,),
        )
        current_borrows = (row := cursor.fetchone()) and row.get("total") or 0
        # Kiểm tra nếu vượt quá giới hạn
        if (current_borrows + so_luong_muon) > max_limit:
            raise ValueError(f"Bạn đã vượt quá giới hạn mượn sách ({max_limit} cuốn).")

        # --- Kiểm tra sách ---
        # Khóa sách để kiểm tra và trừ số lượng
        cursor.execute(
            "SELECT so_luong, trang_thai FROM Sach WHERE id_sach = %s FOR UPDATE",
            (id_sach,),
        )
        sach = cursor.fetchone()
        # Kiểm tra tồn tại, trạng thái và số lượng
        if not sach or sach.get("trang_thai") == "da_an":
            raise ValueError("Sách không có sẵn hoặc đã bị ẩn.")
        if so_luong_muon > sach.get("so_luong", 0):
            raise ValueError(
                f"Số lượng sách trong kho không đủ (còn {sach.get('so_luong', 0)})."
            )

        # --- Tạo bản ghi mượn trả ---
        # Thêm bản ghi vào MuonTra với trạng thái 'Đang chờ'
        # Lưu ý: ngay_muon lưu ngày hẹn lấy
        cursor.execute(
            """ INSERT INTO MuonTra (id_sach, id_thanh_vien, ngay_muon, ngay_hen_tra, so_luong, trang_thai)
                VALUES (%s, %s, %s, %s, %s, 'Đang chờ') """,
            (id_sach, current_user.id, ngay_lay, ngay_tra, so_luong_muon),
        )
        # Trừ số lượng sách (tạm giữ) trong bảng Sach
        cursor.execute(
            "UPDATE Sach SET so_luong = so_luong - %s WHERE id_sach = %s",
            (so_luong_muon, id_sach),
        )

        conn.commit()  # Lưu thay đổi
        return jsonify(
            success=True, message="Đặt lịch mượn sách thành công!"
        )  # Trả về thành công

    # --- Xử lý lỗi ---
    except (ValueError, KeyError) as ve:  # Lỗi validation hoặc thiếu key form
        if conn and conn.in_transaction:
            conn.rollback()
        print(f"!!! Lỗi dữ liệu form mượn sách user {current_user.id}: {ve}")
        return jsonify(success=False, error=f"Dữ liệu không hợp lệ: {ve}"), 400
    except mysql.connector.Error as err:  # Lỗi CSDL
        if conn and conn.in_transaction:
            conn.rollback()
        print(f"!!! Lỗi CSDL khi user {current_user.id} mượn sách {id_sach}: {err}")
        return jsonify(success=False, error="Lỗi cơ sở dữ liệu."), 500
    except Exception as e:  # Lỗi không xác định khác
        if conn and conn.in_transaction:
            conn.rollback()
        print(
            f"!!! Lỗi không xác định khi user {current_user.id} mượn sách {id_sach}: {e}"
        )
        return jsonify(success=False, error="Lỗi không xác định xảy ra."), 500
    finally:
        # Đảm bảo đóng kết nối
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# ROUTE: ĐỘC GIẢ HỦY ĐƠN ĐẶT SÁCH ("/profile/muontra/huy/<id>") - AJAX
# =========================================================
@profile_bp.route("/profile/muontra/huy/<int:id_muon_tra>", methods=["POST"])
@login_required  # Yêu cầu đăng nhập
def user_huy_dat_sach(id_muon_tra):
    """
    Xử lý yêu cầu độc giả hủy đơn đặt sách đang ở trạng thái 'Đang chờ' của chính họ.
    Chuyển trạng thái thành 'Đã hủy', ghi ngày hủy.
    Hoàn trả số lượng sách về kho.
    Trả về: JSON thông báo thành công hoặc lỗi.
    """
    # Chỉ cho phép độc giả hủy
    if current_user.vai_tro != "doc_gia":
        return jsonify(success=False, error="Chỉ độc giả mới có thể hủy đơn đặt."), 403

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()  # Bắt đầu transaction

        # Lấy thông tin lượt đặt và khóa bản ghi (FOR UPDATE)
        # Chỉ lấy nếu đúng ID, trạng thái 'Đang chờ' VÀ đúng ID của người dùng hiện tại
        cursor.execute(
            """ SELECT id_sach, so_luong FROM MuonTra WHERE id_muon_tra = %s AND trang_thai = 'Đang chờ'
                AND id_thanh_vien = %s FOR UPDATE """,  # Thêm id_thanh_vien vào WHERE
            (id_muon_tra, current_user.id),
        )
        record = cursor.fetchone()

        # Kiểm tra xem có tìm thấy bản ghi hợp lệ không
        if not record:
            conn.rollback()
            return (
                jsonify(success=False, error="Không tìm thấy lượt đặt hợp lệ để hủy."),
                404,
            )

        id_sach = record["id_sach"]
        so_luong_dat = record["so_luong"]

        # Cập nhật trạng thái lượt đặt thành 'Đã hủy' và ghi ngày hủy (vào cột ngay_tra_thuc)
        cursor.execute(
            "UPDATE MuonTra SET trang_thai = 'Đã hủy', ngay_tra_thuc = %s WHERE id_muon_tra = %s",
            (datetime.datetime.now(), id_muon_tra),
        )

        # Khóa sách để cộng lại số lượng (FOR UPDATE)
        cursor.execute(
            "SELECT id_sach FROM Sach WHERE id_sach = %s FOR UPDATE", (id_sach,)
        )
        cursor.fetchone()  # Phải fetch
        # Cộng lại số lượng sách vào kho
        cursor.execute(
            "UPDATE Sach SET so_luong = so_luong + %s WHERE id_sach = %s",
            (so_luong_dat, id_sach),
        )

        conn.commit()  # Lưu thay đổi
        return jsonify(
            success=True,
            message="Đã hủy đơn đặt thành công. Sách đã được hoàn trả về kho.",
        )

    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        print(f"!!! Lỗi DB khi user {current_user.id} hủy đơn {id_muon_tra}: {err}")
        return jsonify(success=False, error=f"Lỗi cơ sở dữ liệu: {err}"), 500
    except Exception as e:
        if conn:
            conn.rollback()
        print(
            f"!!! Lỗi không xác định khi user {current_user.id} hủy đơn {id_muon_tra}: {e}"
        )
        return jsonify(success=False, error=f"Lỗi không xác định: {e}"), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# =========================================================
# ROUTE: ĐỘC GIẢ GIA HẠN SÁCH ("/profile/muontra/giahan/<id>") - AJAX
# =========================================================
@profile_bp.route("/profile/muontra/giahan/<int:id_muon_tra>", methods=["POST"])
@login_required  # Yêu cầu đăng nhập
def gia_han_sach(id_muon_tra):
    """
    Xử lý yêu cầu độc giả gia hạn sách đang mượn của chính họ.
    Kiểm tra xem sách có đang mượn và chưa quá hạn không.
    Lấy thời hạn gia hạn từ cài đặt ('thoi_han_gia_han').
    Cập nhật ngày hẹn trả mới trong CSDL.
    Trả về: JSON thông báo thành công/lỗi và ngày hẹn trả mới.
    """
    # Chỉ cho phép độc giả gia hạn
    if current_user.vai_tro != "doc_gia":
        return jsonify(success=False, error="Chức năng này chỉ dành cho độc giả."), 403

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        conn.start_transaction()  # Bắt đầu transaction

        # Lấy thông tin lượt mượn và khóa bản ghi (FOR UPDATE)
        # Chỉ lấy nếu đúng ID, đúng user, VÀ trạng thái là 'Đang mượn'
        cursor.execute(
            """ SELECT id_muon_tra, ngay_hen_tra FROM MuonTra
                WHERE id_muon_tra = %s AND id_thanh_vien = %s AND trang_thai = 'Đang mượn' FOR UPDATE """,
            (id_muon_tra, current_user.id),
        )
        record = cursor.fetchone()

        # Kiểm tra xem có tìm thấy lượt mượn hợp lệ không
        if not record:
            conn.rollback()
            return (
                jsonify(
                    success=False, error="Không tìm thấy lượt mượn hợp lệ để gia hạn."
                ),
                404,
            )

        # Kiểm tra xem sách có bị quá hạn không
        ngay_hen_tra_hien_tai = record["ngay_hen_tra"]
        if ngay_hen_tra_hien_tai < datetime.date.today():
            conn.rollback()
            return (
                jsonify(success=False, error="Không thể gia hạn sách đã quá hạn."),
                400,
            )

        # Lấy số ngày gia hạn từ cài đặt
        cursor.execute(
            "SELECT setting_value FROM CaiDat WHERE setting_key = 'thoi_han_gia_han'"
        )
        setting = cursor.fetchone()
        try:  # Xử lý nếu cài đặt không hợp lệ hoặc thiếu
            so_ngay_gia_han = (
                int(setting["setting_value"])
                if setting and setting.get("setting_value", "").isdigit()
                else 7
            )
        except (ValueError, TypeError):
            so_ngay_gia_han = 7
        if so_ngay_gia_han <= 0:
            so_ngay_gia_han = 7  # Đảm bảo số ngày > 0

        # Tính ngày hẹn trả mới
        ngay_hen_tra_moi = ngay_hen_tra_hien_tai + datetime.timedelta(
            days=so_ngay_gia_han
        )

        # Cập nhật ngày hẹn trả mới vào CSDL
        cursor.execute(
            "UPDATE MuonTra SET ngay_hen_tra = %s WHERE id_muon_tra = %s",
            (ngay_hen_tra_moi, id_muon_tra),
        )
        # (Không cần ghi log admin vì đây là hành động của user)
        conn.commit()  # Lưu thay đổi

        # Trả về JSON thành công cùng ngày hẹn trả mới (đã định dạng)
        return jsonify(
            success=True,
            message=f"Gia hạn thành công đến ngày {ngay_hen_tra_moi.strftime('%d-%m-%Y')}.",
            new_due_date=ngay_hen_tra_moi.strftime(
                "%d-%m-%Y"
            ),  # Gửi ngày mới cho JS cập nhật UI
        )

    except mysql.connector.Error as err:
        if conn:
            conn.rollback()
        print(
            f"!!! Lỗi DB khi user {current_user.id} gia hạn sách {id_muon_tra}: {err}"
        )
        return jsonify(success=False, error=f"Lỗi cơ sở dữ liệu: {err}"), 500
    except Exception as e:
        if conn:
            conn.rollback()
        print(
            f"!!! Lỗi không xác định khi user {current_user.id} gia hạn sách {id_muon_tra}: {e}"
        )
        return jsonify(success=False, error=f"Lỗi không xác định: {e}"), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()
