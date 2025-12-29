# app_copy.py
# =========================================================
# FILE CHÍNH CỦA ỨNG DỤNG FLASK (SAU KHI TÁCH FILE)
# File này chịu trách nhiệm:
# - Khởi tạo ứng dụng Flask.
# - Tải cấu hình từ biến môi trường.
# - Khởi tạo các extension cần thiết (LoginManager, CSRFProtect).
# - Import và đăng ký các Blueprints (chứa các routes).
# - Cấu hình các thành phần cốt lõi như quản lý đăng nhập, context processor.
# - Chạy server Flask (khi được thực thi trực tiếp).
# =========================================================

import os  # Module thao tác với hệ điều hành (đọc biến môi trường, tạo đường dẫn)
from dotenv import load_dotenv  # Thư viện để tải biến môi trường từ file .env
from flask import Flask  # Lớp chính để tạo ứng dụng Flask
from flask_login import LoginManager  # Extension quản lý session đăng nhập
from flask_wtf.csrf import CSRFProtect  # Extension bảo vệ chống tấn công CSRF

# --- 1. Tải biến môi trường ---
# =========================================================
# Tải các biến cấu hình (như database credentials, secret key) từ file .env
# Giúp tách biệt cấu hình nhạy cảm khỏi code.
# =========================================================
load_dotenv()

# --- 2. Import các Blueprints từ thư mục app_logic ---
# =========================================================
# Blueprints giúp module hóa ứng dụng, chia routes thành các nhóm logic.
# Mỗi file .py chứa một nhóm routes liên quan (ví dụ: auth, admin, core).
# =========================================================
from app_logic.auth_routes import auth_bp  # Routes xác thực (login, register, logout)
from app_logic.admin_routes import admin_bp  # Routes quản trị
from app_logic.core_routes import (
    core_bp,
)  # Routes chính của người dùng (trang chủ, xem sách)
from app_logic.profile_routes import profile_bp  # Routes hồ sơ người dùng
from app_logic.api_routes import api_bp  # Routes API (dùng cho AJAX)

# --- 3. Import các hàm/lớp cần thiết ở cấp độ ứng dụng ---
# =========================================================
# Import các thành phần sẽ được sử dụng trực tiếp bởi đối tượng app
# hoặc các extension được khởi tạo ở đây.
# =========================================================
from app_logic.models import (
    load_user_callback,
)  # Hàm để LoginManager tải thông tin user từ ID
from app_logic.utils import slugify  # Hàm tạo slug (dùng trong context processor)

# --- 4. Khởi tạo ứng dụng Flask ---
# =========================================================
# Tạo một instance của lớp Flask.
# __name__: Tên của module hiện tại, giúp Flask xác định vị trí tài nguyên (templates, static).
# =========================================================
app = Flask(__name__)

# --- 5. Cấu hình ứng dụng ---
# =========================================================
# Thiết lập các biến cấu hình cho ứng dụng Flask.
# - SECRET_KEY: Bắt buộc cho session management, CSRF protection. Nên lấy từ biến môi trường.
# - UPLOAD_FOLDER: Đường dẫn thư mục lưu file upload (ảnh bìa, avatar).
# - ALLOWED_EXTENSIONS: Các đuôi file ảnh được phép upload.
# =========================================================
# Lấy SECRET_KEY từ biến môi trường, có giá trị fallback nếu không tìm thấy
app.config["SECRET_KEY"] = os.getenv(
    "FLASK_SECRET_KEY", "a-very-secret-fallback-key-change-me"
)
# Xác định đường dẫn tuyệt đối đến thư mục 'static' (nơi lưu file upload)
UPLOAD_FOLDER = os.path.join(app.root_path, "static")
AVATAR_FOLDER = os.path.join(UPLOAD_FOLDER, "uploads", "avatars")
COVER_FOLDER = os.path.join(UPLOAD_FOLDER, "uploads", "covers")

# Tự động tạo các thư mục này nếu chưa tồn tại
os.makedirs(AVATAR_FOLDER, exist_ok=True)
os.makedirs(COVER_FOLDER, exist_ok=True)
# Định nghĩa các đuôi file ảnh được phép
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
# Lưu cấu hình vào app.config để các phần khác của ứng dụng có thể truy cập
app.config["AVATAR_FOLDER"] = AVATAR_FOLDER  # Thêm dòng này
app.config["COVER_FOLDER"] = COVER_FOLDER    # Thêm dòng này
app.config["ALLOWED_EXTENSIONS"] = ALLOWED_EXTENSIONS
# (Có thể thêm các cấu hình khác nếu cần, ví dụ: database URI nếu dùng SQLAlchemy)

# --- 6. Khởi tạo các Extension ---
# =========================================================
# Khởi tạo các đối tượng extension và liên kết chúng với ứng dụng Flask (app).
# =========================================================
csrf = CSRFProtect(app)  # Bật tính năng bảo vệ CSRF cho toàn bộ ứng dụng
login_manager = LoginManager()  # Tạo đối tượng quản lý đăng nhập
login_manager.init_app(app)  # Liên kết LoginManager với ứng dụng

# --- 7. Cấu hình LoginManager ---
# =========================================================
# Cấu hình cách LoginManager xử lý việc yêu cầu đăng nhập.
# - login_view: Tên endpoint (bao gồm cả prefix của blueprint) của trang đăng nhập.
#               Flask-Login sẽ redirect đến đây nếu người dùng chưa đăng nhập cố gắng truy cập trang yêu cầu @login_required.
# - login_message: Thông báo flash hiển thị khi người dùng bị redirect đến trang đăng nhập.
# - login_message_category: Loại (category) của thông báo flash (vd: 'info', 'warning').
# =========================================================
login_manager.login_view = "auth.login"  # Định nghĩa view đăng nhập (thuộc auth_bp)
login_manager.login_message = "Vui lòng đăng nhập để truy cập trang này."
login_manager.login_message_category = "info"  # Bootstrap class cho thông báo


# --- Đăng ký hàm user_loader ---
# =========================================================
# Hàm này rất quan trọng cho Flask-Login. Nó được gọi mỗi khi cần lấy
# thông tin người dùng từ ID lưu trong session. Hàm này phải trả về
# một đối tượng User (từ models.py) hoặc None nếu không tìm thấy user.
# =========================================================
@login_manager.user_loader
def load_user(user_id):
    """Callback function used by Flask-Login to reload the user object from the user ID stored in the session."""
    return load_user_callback(user_id)  # Gọi hàm đã import từ models.py


# --- 8. Đăng ký Context Processor ---
# =========================================================
# Context processors làm cho các biến hoặc hàm có sẵn trong tất cả các template Jinja2
# mà không cần truyền chúng một cách tường minh trong mỗi hàm render_template.
# Ở đây, hàm slugify được đưa vào context để có thể dùng trong các template (vd: tạo URL thân thiện).
# =========================================================
@app.context_processor
def utility_processor():
    """Làm cho hàm slugify có sẵn trong mọi template."""
    return dict(
        slugify=slugify
    )  # Trả về một dict, key là tên biến trong template, value là hàm/biến Python


# --- 9. Đăng ký các Blueprint ---
# =========================================================
# Liên kết các Blueprints đã import với ứng dụng Flask chính.
# Khi đăng ký, Flask sẽ biết về các routes được định nghĩa trong mỗi Blueprint.
# Các URL prefix (nếu có, như '/admin' cho admin_bp) cũng được áp dụng ở đây.
# =========================================================
app.register_blueprint(auth_bp)  # Đăng ký blueprint xác thực
app.register_blueprint(admin_bp)  # Đăng ký blueprint quản trị
app.register_blueprint(core_bp)  # Đăng ký blueprint cốt lõi
app.register_blueprint(profile_bp)  # Đăng ký blueprint hồ sơ
app.register_blueprint(api_bp)  # Đăng ký blueprint API

# --- 10. Chạy ứng dụng ---
# =========================================================
# Khối này chỉ thực thi khi file app_copy.py được chạy trực tiếp (python app_copy.py).
# app.run() khởi động server phát triển tích hợp của Flask.
# debug=True: Bật chế độ debug, tự động tải lại khi code thay đổi và hiển thị traceback lỗi chi tiết trên trình duyệt.
#             CHỈ NÊN DÙNG KHI PHÁT TRIỂN. Tắt (debug=False) khi triển khai thực tế.
# =========================================================
if __name__ == "__main__":
    app.run(debug=True)  # Chạy server Flask ở chế độ debug
