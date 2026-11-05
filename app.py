import os
import uuid

from decimal import Decimal, InvalidOperation
from functools import wraps
from datetime import timedelta

from dotenv import load_dotenv

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_connection


# ==================================================
# 1. FLASK CONFIGURATION
# ==================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)

app.secret_key = os.environ.get("FLASK_SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY is missing. Check your .env file."
    )

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("FLASK_HTTPS", "0") == "1"
)

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

MAX_FILE_SIZE = 5 * 1024 * 1024

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

CLOTHING_SIZES = ["XS", "S", "M", "L", "XL", "XXL"]
ALL_SIZES = CLOTHING_SIZES + ["One Size"]

ACCESSORY_CATEGORY = "accessories"


# ==================================================
# 2. HELPER FUNCTIONS
# ==================================================

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def is_accessory(category_name):
    return (
        (category_name or "").strip().lower()
        == ACCESSORY_CATEGORY
    )


def admin_required(function):

    @wraps(function)
    def decorated_function(*args, **kwargs):

        if (
            "user_id" not in session
            or session.get("role") != "admin"
        ):
            session.clear()
            flash("Please log in with an admin account.")
            return redirect(url_for("admin_login"))

        return function(*args, **kwargs)

    return decorated_function


def customer_required(function):

    @wraps(function)
    def decorated_function(*args, **kwargs):

        if (
            "user_id" not in session
            or session.get("role") != "customer"
        ):
            flash("Please log in with your customer account.")
            return redirect(url_for("customer_login"))

        return function(*args, **kwargs)

    return decorated_function


def get_product_sizes(cursor, product_id):

    cursor.execute("""
        SELECT size, stock
        FROM product_sizes
        WHERE product_id = %s
        ORDER BY FIELD(
            size,
            'XS', 'S', 'M', 'L', 'XL', 'XXL', 'One Size'
        )
    """, (product_id,))

    return cursor.fetchall()


def sync_total_stock(cursor, product_id):

    cursor.execute("""
        SELECT COALESCE(SUM(stock), 0) AS total_stock
        FROM product_sizes
        WHERE product_id = %s
    """, (product_id,))

    total_stock = cursor.fetchone()["total_stock"]

    cursor.execute("""
        UPDATE products
        SET stock = %s
        WHERE product_id = %s
    """, (total_stock, product_id))


def save_uploaded_image(image):

    if not image or not image.filename:
        return None

    if not allowed_file(image.filename):
        raise ValueError(
            "Only JPG, JPEG, PNG and WebP images are allowed."
        )

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    safe_name = secure_filename(image.filename)

    if "." not in safe_name:
        raise ValueError("Invalid image filename.")

    extension = safe_name.rsplit(".", 1)[1].lower()

    filename = f"{uuid.uuid4().hex}.{extension}"

    image_path = os.path.join(
        UPLOAD_FOLDER,
        filename
    )

    image.save(image_path)

    return f"uploads/{filename}", image_path


def remove_product_image(image_url):

    if not image_url:
        return

    image_path = os.path.join(
        BASE_DIR,
        "static",
        image_url
    )

    if os.path.isfile(image_path):

        try:
            os.remove(image_path)

        except OSError:
            pass


def get_valid_price(price_text):

    try:

        price = Decimal(price_text)

        if not price.is_finite() or price < 0:
            return None

        if price > Decimal("99999999.99"):
            return None

        return price

    except (InvalidOperation, ValueError, TypeError):
        return None


def get_valid_category(cursor, category_id):

    try:
        category_id = int(category_id)

    except (ValueError, TypeError):
        return None

    cursor.execute("""
        SELECT category_id, category_name
        FROM categories
        WHERE category_id = %s
    """, (category_id,))

    return cursor.fetchone()


def get_size_stock(form, selected_sizes):

    size_stock = {}

    try:

        for size in selected_sizes:

            quantity = int(
                form.get(f"stock_{size}", "0")
            )

            if quantity < 0:
                return None

            size_stock[size] = quantity

    except (ValueError, TypeError):
        return None

    return size_stock


def update_size_inventory(cursor, product_id, size_stock):

    for size, quantity in size_stock.items():

        cursor.execute("""
            INSERT INTO product_sizes
                (product_id, size, stock)
            VALUES (%s, %s, %s)

            ON DUPLICATE KEY UPDATE
                stock = VALUES(stock)
        """, (
            product_id,
            size,
            quantity
        ))

    selected_sizes = list(size_stock.keys())

    if selected_sizes:

        placeholders = ", ".join(
            ["%s"] * len(selected_sizes)
        )

        cursor.execute(f"""
            DELETE FROM product_sizes
            WHERE product_id = %s
            AND size NOT IN ({placeholders})
        """, [product_id] + selected_sizes)

    sync_total_stock(cursor, product_id)


def get_active_products(cursor, category=None):

    query = """
        SELECT
            p.product_id,
            p.product_name,
            p.description,
            p.price,
            p.image_url,
            p.stock,
            c.category_name

        FROM products p

        LEFT JOIN categories c
            ON p.category_id = c.category_id

        WHERE p.is_active = TRUE
    """

    params = []

    if category:
        query += " AND c.category_name = %s"
        params.append(category)

    query += " ORDER BY p.created_at DESC"

    cursor.execute(query, params)

    products = cursor.fetchall()

    for product in products:

        product["sizes"] = get_product_sizes(
            cursor,
            product["product_id"]
        )

    return products


def get_safe_cart():

    cart = session.get("cart", {})

    if not isinstance(cart, dict):
        return {}

    return cart


def add_item_to_cart(product_id, size):

    if size not in ALL_SIZES:
        return False, "Please select a valid size."

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                p.product_id,
                p.product_name,
                ps.stock,
                c.category_name

            FROM products p

            JOIN product_sizes ps
                ON ps.product_id = p.product_id

            LEFT JOIN categories c
                ON p.category_id = c.category_id

            WHERE p.product_id = %s
              AND p.is_active = TRUE
              AND ps.size = %s
        """, (product_id, size))

        product = cursor.fetchone()

        if not product:
            return False, "This size is not available."

        if is_accessory(product["category_name"]):

            if size != "One Size":
                return False, "Invalid size for this accessory."

        elif size not in CLOTHING_SIZES:
            return False, "Invalid clothing size."

        if product["stock"] <= 0:
            return False, "This size is sold out."

        cart = get_safe_cart()

        cart_key = f"{product_id}_{size}"

        current_item = cart.get(cart_key, {})

        try:
            current_quantity = int(
                current_item.get("quantity", 0)
            )

        except (ValueError, TypeError, AttributeError):
            current_quantity = 0

        current_quantity = max(current_quantity, 0)

        if current_quantity >= product["stock"]:
            return False, "Maximum available quantity already added."

        cart[cart_key] = {
            "product_id": product_id,
            "size": size,
            "quantity": current_quantity + 1
        }

        session["cart"] = cart
        session.modified = True

        return True, (
            f"{product['product_name']} ({size}) added to your cart!"
        )

    finally:
        cursor.close()
        connection.close()


# ==================================================
# 3. HOME PAGE
# ==================================================

@app.route("/")
def home():

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        products = get_active_products(cursor)

        return render_template(
            "home.html",
            products=products
        )

    finally:
        cursor.close()
        connection.close()


# ==================================================
# 4. ADMIN LOGIN
# ==================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    if session.get("role") == "admin":
        return redirect(url_for("admin"))

    if request.method == "POST":

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get(
            "password", ""
        )

        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        try:

            cursor.execute("""
                SELECT
                    user_id,
                    full_name,
                    email,
                    password_hash,
                    role

                FROM users

                WHERE email = %s
            """, (email,))

            user = cursor.fetchone()

            if (
                user
                and user["role"] == "admin"
                and check_password_hash(
                    user["password_hash"],
                    password
                )
            ):

                session.clear()

                session["user_id"] = user["user_id"]
                session["user_name"] = user["full_name"]
                session["role"] = "admin"

                session.permanent = True

                return redirect(url_for("admin"))

            flash("Invalid email or password.")

        finally:
            cursor.close()
            connection.close()

    return render_template("admin_login.html")


# ==================================================
# 5. ADMIN LOGOUT
# ==================================================

@app.route("/admin/logout", methods=["POST"])
@admin_required
def admin_logout():

    session.clear()

    flash("You have been logged out.")

    return redirect(url_for("admin_login"))


# ==================================================
# 6. CUSTOMER REGISTRATION
# ==================================================

@app.route("/register", methods=["GET", "POST"])
def customer_register():

    if session.get("role") == "customer":
        return redirect(url_for("shop"))

    if request.method == "POST":

        full_name = request.form.get(
            "full_name", ""
        ).strip()

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get("password", "")

        confirm_password = request.form.get(
            "confirm_password", ""
        )

        if not full_name or not email or not password:
            flash("Please complete all required fields.")
            return redirect(url_for("customer_register"))

        if len(full_name) > 100 or len(email) > 150:
            flash("Name or email is too long.")
            return redirect(url_for("customer_register"))

        if len(password) < 8:
            flash("Password must be at least 8 characters long.")
            return redirect(url_for("customer_register"))

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for("customer_register"))

        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        try:

            cursor.execute("""
                SELECT user_id
                FROM users
                WHERE email = %s
            """, (email,))

            if cursor.fetchone():
                flash(
                    "An account with this email already exists. "
                    "Please log in."
                )
                return redirect(url_for("customer_login"))

            password_hash = generate_password_hash(password)

            cursor.execute("""
                INSERT INTO users
                    (full_name, email, password_hash, role)
                VALUES (%s, %s, %s, 'customer')
            """, (
                full_name,
                email,
                password_hash
            ))

            connection.commit()

            user_id = cursor.lastrowid

            existing_cart = get_safe_cart()
            pending_cart_item = session.get("pending_cart_item")

            session.clear()

            session["cart"] = existing_cart

            if pending_cart_item:
                session["pending_cart_item"] = pending_cart_item

            session["user_id"] = user_id
            session["user_name"] = full_name
            session["role"] = "customer"

            session.permanent = True

            flash("Your account has been created successfully.")

            if session.get("pending_cart_item"):
                return redirect(url_for("complete_pending_cart"))

            return redirect(url_for("shop"))

        except Exception:
            connection.rollback()
            raise

        finally:
            cursor.close()
            connection.close()

    return render_template("customer_register.html")


# ==================================================
# 7. CUSTOMER LOGIN
# ==================================================

@app.route("/login", methods=["GET", "POST"])
def customer_login():

    if session.get("role") == "customer":
        return redirect(url_for("shop"))

    if request.method == "POST":

        email = request.form.get(
            "email", ""
        ).strip().lower()

        password = request.form.get("password", "")

        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        try:

            cursor.execute("""
                SELECT
                    user_id,
                    full_name,
                    email,
                    password_hash,
                    role

                FROM users

                WHERE email = %s
            """, (email,))

            user = cursor.fetchone()

            if (
                user
                and user["role"] == "customer"
                and check_password_hash(
                    user["password_hash"],
                    password
                )
            ):

                pending_cart_item = session.get("pending_cart_item")
                existing_cart = get_safe_cart()

                session.clear()

                session["cart"] = existing_cart

                if pending_cart_item:
                    session["pending_cart_item"] = pending_cart_item

                session["user_id"] = user["user_id"]
                session["user_name"] = user["full_name"]
                session["role"] = "customer"

                session.permanent = True

                flash("Welcome back!")

                if pending_cart_item:
                    return redirect(url_for("complete_pending_cart"))

                return redirect(url_for("cart"))

            flash("Invalid email or password.")

        finally:
            cursor.close()
            connection.close()

    return render_template("customer_login.html")


# ==================================================
# 8. CUSTOMER LOGOUT
# ==================================================

@app.route("/logout", methods=["POST"])
@customer_required
def customer_logout():

    existing_cart = get_safe_cart()

    session.clear()

    session["cart"] = existing_cart

    flash("You have been logged out.")

    return redirect(url_for("home"))


# ==================================================
# 9. RESTORE PENDING CART ITEM AFTER LOGIN
# ==================================================

@app.route("/complete-pending-cart")
@customer_required
def complete_pending_cart():

    pending_item = session.pop("pending_cart_item", None)

    if not isinstance(pending_item, dict):
        return redirect(url_for("cart"))

    try:

        product_id = int(pending_item.get("product_id"))
        size = pending_item.get("size", "")

    except (ValueError, TypeError):

        flash("We could not restore that cart item. Please try again.")

        return redirect(url_for("shop"))

    success, message = add_item_to_cart(product_id, size)

    flash(message)

    return redirect(
        url_for("cart" if success else "shop")
    )


# ==================================================
# 10. SHOP PAGE
# ==================================================

@app.route("/shop")
def shop():

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        category = request.args.get(
            "category", ""
        ).strip()

        products = get_active_products(
            cursor,
            category if category else None
        )

        return render_template(
            "shop.html",
            products=products
        )

    finally:
        cursor.close()
        connection.close()


# ==================================================
# 11. ADMIN DASHBOARD
# ADD AND VIEW PRODUCTS
# ==================================================

@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    image_path = None

    try:

        if request.method == "POST":

            name = request.form.get(
                "product_name", ""
            ).strip()

            description = request.form.get(
                "description", ""
            ).strip()

            price = get_valid_price(
                request.form.get("price", "")
            )

            category = get_valid_category(
                cursor,
                request.form.get("category_id", "")
            )

            image = request.files.get("image")

            if not name or not category or price is None:

                flash("Please enter valid product details.")

                return redirect(url_for("admin"))

            if not image or not image.filename:

                flash("Please select a product image.")

                return redirect(url_for("admin"))

            if not allowed_file(image.filename):

                flash("Upload a JPG, PNG or WebP image.")

                return redirect(url_for("admin"))

            if is_accessory(category["category_name"]):

                selected_sizes = ["One Size"]

            else:

                selected_sizes = list(
                    dict.fromkeys(
                        request.form.getlist("sizes")
                    )
                )

                if (
                    not selected_sizes
                    or any(
                        size not in CLOTHING_SIZES
                        for size in selected_sizes
                    )
                ):

                    flash("Select at least one clothing size.")

                    return redirect(url_for("admin"))

            size_stock = get_size_stock(
                request.form,
                selected_sizes
            )

            if size_stock is None:

                flash("Enter valid non-negative stock quantities.")

                return redirect(url_for("admin"))

            total_stock = sum(size_stock.values())

            try:

                saved_image = save_uploaded_image(image)

                image_url, image_path = saved_image

                cursor.execute("""
                    INSERT INTO products (
                        product_name,
                        description,
                        price,
                        image_url,
                        category_id,
                        stock
                    )

                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    name,
                    description,
                    price,
                    image_url,
                    category["category_id"],
                    total_stock
                ))

                product_id = cursor.lastrowid

                update_size_inventory(
                    cursor,
                    product_id,
                    size_stock
                )

                connection.commit()

                flash("Product added successfully!")

                image_path = None

            except Exception:

                connection.rollback()

                if image_path and os.path.exists(image_path):
                    os.remove(image_path)

                raise

            return redirect(url_for("admin"))

        cursor.execute("""
            SELECT category_id, category_name
            FROM categories
            ORDER BY category_name
        """)

        categories = cursor.fetchall()

        cursor.execute("""
            SELECT
                p.product_id,
                p.product_name,
                p.description,
                p.price,
                p.stock,
                p.image_url,
                p.category_id,
                p.is_active,
                c.category_name

            FROM products p

            LEFT JOIN categories c
                ON p.category_id = c.category_id

            ORDER BY p.created_at DESC
        """)

        products = cursor.fetchall()

        for product in products:

            product["sizes"] = get_product_sizes(
                cursor,
                product["product_id"]
            )

        return render_template(
            "admin.html",
            categories=categories,
            products=products,
            clothing_sizes=CLOTHING_SIZES
        )

    finally:
        cursor.close()
        connection.close()


# ==================================================
# 12. UPDATE PRODUCT SIZE INVENTORY
# ==================================================

@app.route(
    "/admin/update-sizes/<int:product_id>",
    methods=["POST"]
)
@admin_required
def update_product_sizes(product_id):

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                p.product_id,
                c.category_name

            FROM products p

            LEFT JOIN categories c
                ON p.category_id = c.category_id

            WHERE p.product_id = %s
        """, (product_id,))

        product = cursor.fetchone()

        if not product:

            flash("Product not found.")

            return redirect(url_for("admin"))

        if is_accessory(product["category_name"]):

            selected_sizes = ["One Size"]

        else:

            selected_sizes = list(
                dict.fromkeys(
                    request.form.getlist("sizes")
                )
            )

            if (
                not selected_sizes
                or any(
                    size not in CLOTHING_SIZES
                    for size in selected_sizes
                )
            ):

                flash("Select at least one valid clothing size.")

                return redirect(url_for("admin"))

        size_stock = get_size_stock(
            request.form,
            selected_sizes
        )

        if size_stock is None:

            flash("Enter valid non-negative quantities.")

            return redirect(url_for("admin"))

        update_size_inventory(
            cursor,
            product_id,
            size_stock
        )

        connection.commit()

        flash("Size inventory updated successfully.")

    except Exception:

        connection.rollback()

        raise

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("admin"))


# ==================================================
# 13. EDIT PRODUCT DETAILS
# ==================================================

@app.route(
    "/admin/edit-product/<int:product_id>",
    methods=["POST"]
)
@admin_required
def edit_product(product_id):

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    new_image_path = None

    try:

        name = request.form.get(
            "product_name", ""
        ).strip()

        description = request.form.get(
            "description", ""
        ).strip()

        price = get_valid_price(
            request.form.get("price", "")
        )

        category = get_valid_category(
            cursor,
            request.form.get("category_id", "")
        )

        if not name or price is None or not category:

            flash("Enter valid product details.")

            return redirect(url_for("admin"))

        cursor.execute("""
            SELECT
                p.image_url,
                c.category_name

            FROM products p

            LEFT JOIN categories c
                ON p.category_id = c.category_id

            WHERE p.product_id = %s
        """, (product_id,))

        existing = cursor.fetchone()

        if not existing:

            flash("Product not found.")

            return redirect(url_for("admin"))

        old_is_accessory = is_accessory(
            existing["category_name"]
        )

        new_is_accessory = is_accessory(
            category["category_name"]
        )

        if old_is_accessory != new_is_accessory:

            flash(
                "You cannot change between clothing and accessories "
                "categories for an existing product. Create a new "
                "product with the correct category instead."
            )

            return redirect(url_for("admin"))

        image_url = existing["image_url"]

        image = request.files.get("image")

        if image and image.filename:

            if not allowed_file(image.filename):

                flash("Upload a JPG, PNG or WebP image.")

                return redirect(url_for("admin"))

            saved_image = save_uploaded_image(image)

            image_url, new_image_path = saved_image

        cursor.execute("""
            UPDATE products

            SET product_name = %s,
                description = %s,
                price = %s,
                category_id = %s,
                image_url = %s

            WHERE product_id = %s
        """, (
            name,
            description,
            price,
            category["category_id"],
            image_url,
            product_id
        ))

        connection.commit()

        if new_image_path:
            remove_product_image(existing["image_url"])

        flash("Product details updated successfully.")

    except Exception:

        connection.rollback()

        if new_image_path and os.path.exists(new_image_path):
            os.remove(new_image_path)

        raise

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("admin"))


# ==================================================
# 14. HIDE OR SHOW PRODUCT
# ==================================================

@app.route(
    "/admin/toggle-product/<int:product_id>",
    methods=["POST"]
)
@admin_required
def toggle_product(product_id):

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT is_active
            FROM products
            WHERE product_id = %s
        """, (product_id,))

        product = cursor.fetchone()

        if not product:

            flash("Product not found.")

        else:

            new_status = not bool(product["is_active"])

            cursor.execute("""
                UPDATE products
                SET is_active = %s
                WHERE product_id = %s
            """, (
                new_status,
                product_id
            ))

            connection.commit()

            if new_status:
                flash("Product is now visible in the shop.")

            else:
                flash("Product has been hidden from the shop.")

    except Exception:

        connection.rollback()

        raise

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("admin"))


# ==================================================
# 15. DELETE PRODUCT
# ==================================================

@app.route(
    "/admin/delete-product/<int:product_id>",
    methods=["POST"]
)
@admin_required
def delete_product(product_id):

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT product_name, image_url
            FROM products
            WHERE product_id = %s
        """, (product_id,))

        product = cursor.fetchone()

        if not product:

            flash("Product not found.")

            return redirect(url_for("admin"))

        cursor.execute("""
            SELECT COUNT(*) AS order_count
            FROM order_items
            WHERE product_id = %s
        """, (product_id,))

        order_count = cursor.fetchone()["order_count"]

        if order_count > 0:

            flash(
                "This product has order history and cannot be "
                "permanently deleted. Hide it instead."
            )

            return redirect(url_for("admin"))

        cursor.execute("""
            DELETE FROM products
            WHERE product_id = %s
        """, (product_id,))

        connection.commit()

        remove_product_image(product["image_url"])

        flash("Product deleted successfully.")

    except Exception:

        connection.rollback()

        raise

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("admin"))


# ==================================================
# 16. ABOUT PAGE
# ==================================================

@app.route("/about")
def about():
    return render_template("about.html")


# ==================================================
# 17. CONTACT PAGE
# ==================================================

@app.route("/contact")
def contact():
    return render_template("contact.html")


# ==================================================
# 18. ADD PRODUCT TO CART
# ==================================================

@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():

    try:
        product_id = int(
            request.form.get("product_id", "")
        )

    except (ValueError, TypeError):

        flash("Invalid product.")

        return redirect(url_for("shop"))

    size = request.form.get("size", "")

    # Guests must log in before adding an item.
    # Save their selected product and size for after login.

    if (
        session.get("role") != "customer"
        or "user_id" not in session
    ):

        if session.get("role") == "admin":

            flash("Please use a customer account to shop.")

            return redirect(url_for("shop"))

        session["pending_cart_item"] = {
            "product_id": product_id,
            "size": size
        }

        session.modified = True

        flash(
            "Please log in or create an account before "
            "adding items to your cart."
        )

        return redirect(url_for("customer_login"))

    success, message = add_item_to_cart(product_id, size)

    flash(message)

    return redirect(
        url_for("cart" if success else "shop")
    )


# ==================================================
# 19. VIEW SHOPPING CART
# ==================================================

@app.route("/cart")
def cart():

    cart_data = get_safe_cart()

    cart_items = []

    subtotal = Decimal("0.00")

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        for cart_key, item in cart_data.items():

            if not isinstance(item, dict):
                continue

            try:

                product_id = int(item["product_id"])
                size = item["size"]
                quantity = int(item["quantity"])

            except (ValueError, TypeError, KeyError):
                continue

            if size not in ALL_SIZES or quantity <= 0:
                continue

            cursor.execute("""
                SELECT
                    p.product_id,
                    p.product_name,
                    p.price,
                    p.image_url,
                    p.is_active,
                    ps.stock

                FROM products p

                JOIN product_sizes ps
                    ON ps.product_id = p.product_id

                WHERE p.product_id = %s
                  AND ps.size = %s
            """, (
                product_id,
                size
            ))

            product = cursor.fetchone()

            if not product or not product["is_active"]:
                continue

            price = Decimal(str(product["price"]))

            line_total = price * quantity

            subtotal += line_total

            cart_items.append({
                "cart_key": cart_key,
                "product_id": product["product_id"],
                "product_name": product["product_name"],
                "price": price,
                "image_url": product["image_url"],
                "stock": product["stock"],
                "size": size,
                "quantity": quantity,
                "line_total": line_total
            })

    finally:
        cursor.close()
        connection.close()

    return render_template(
        "cart.html",
        cart_items=cart_items,
        subtotal=subtotal
    )


# ==================================================
# 20. UPDATE CART QUANTITY
# ==================================================

@app.route("/update-cart", methods=["POST"])
def update_cart():

    cart = get_safe_cart()

    cart_key = request.form.get("cart_key", "")

    if cart_key not in cart:

        flash("Cart item not found.")

        return redirect(url_for("cart"))

    try:

        quantity = int(
            request.form.get("quantity", "")
        )

    except (ValueError, TypeError):

        flash("Enter a valid quantity.")

        return redirect(url_for("cart"))

    if quantity <= 0:

        cart.pop(cart_key, None)

        session["cart"] = cart
        session.modified = True

        flash("Item removed from cart.")

        return redirect(url_for("cart"))

    item = cart[cart_key]

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT
                p.is_active,
                ps.stock

            FROM products p

            JOIN product_sizes ps
                ON ps.product_id = p.product_id

            WHERE p.product_id = %s
              AND ps.size = %s
        """, (
            item["product_id"],
            item["size"]
        ))

        product = cursor.fetchone()

        if not product or not product["is_active"]:

            cart.pop(cart_key, None)

            flash("This product size is no longer available.")

        elif quantity > product["stock"]:

            flash(
                f"Only {product['stock']} units of "
                f"size {item['size']} are available."
            )

        else:

            cart[cart_key]["quantity"] = quantity

            flash("Cart updated successfully.")

        session["cart"] = cart
        session.modified = True

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("cart"))


# ==================================================
# 21. REMOVE PRODUCT FROM CART
# ==================================================

@app.route("/remove-from-cart", methods=["POST"])
def remove_from_cart():

    cart = get_safe_cart()

    cart_key = request.form.get("cart_key", "")

    if cart_key in cart:

        cart.pop(cart_key)

        session["cart"] = cart
        session.modified = True

        flash("Item removed from cart.")

    return redirect(url_for("cart"))


# ==================================================
# 22. CUSTOMER ADDRESS MANAGEMENT
# ==================================================

@app.route("/addresses")
@customer_required
def addresses():

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT *
            FROM customer_addresses
            WHERE user_id = %s
            ORDER BY is_default DESC, created_at DESC
        """, (session["user_id"],))

        saved_addresses = cursor.fetchall()

        return render_template(
            "addresses.html",
            addresses=saved_addresses
        )

    finally:
        cursor.close()
        connection.close()


@app.route("/addresses/add", methods=["POST"])
@customer_required
def add_address():

    fields = {
        "full_name": request.form.get("full_name", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "address_line": request.form.get("address_line", "").strip(),
        "city": request.form.get("city", "").strip(),
        "state": request.form.get("state", "").strip(),
        "pincode": request.form.get("pincode", "").strip(),
        "landmark": request.form.get("landmark", "").strip()
    }

    if not all(fields[key] for key in [
        "full_name", "phone", "address_line",
        "city", "state", "pincode"
    ]):
        flash("Please complete all required address fields.")
        return redirect(url_for("addresses"))

    if (
        len(fields["full_name"]) > 100
        or len(fields["phone"]) > 15
        or len(fields["address_line"]) > 255
        or len(fields["city"]) > 100
        or len(fields["state"]) > 100
        or len(fields["pincode"]) > 10
        or len(fields["landmark"]) > 150
    ):
        flash("One or more address fields are too long.")
        return redirect(url_for("addresses"))

    if not fields["phone"].isdigit() or len(fields["phone"]) < 10:
        flash("Enter a valid phone number.")
        return redirect(url_for("addresses"))

    if not fields["pincode"].isdigit() or len(fields["pincode"]) != 6:
        flash("Enter a valid 6-digit pincode.")
        return redirect(url_for("addresses"))

    make_default = request.form.get("is_default") == "on"

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT COUNT(*) AS address_count
            FROM customer_addresses
            WHERE user_id = %s
        """, (session["user_id"],))

        address_count = cursor.fetchone()["address_count"]

        if address_count == 0:
            make_default = True

        if make_default:
            cursor.execute("""
                UPDATE customer_addresses
                SET is_default = FALSE
                WHERE user_id = %s
            """, (session["user_id"],))

        cursor.execute("""
            INSERT INTO customer_addresses (
                user_id, full_name, phone, address_line,
                city, state, pincode, landmark, is_default
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            session["user_id"],
            fields["full_name"],
            fields["phone"],
            fields["address_line"],
            fields["city"],
            fields["state"],
            fields["pincode"],
            fields["landmark"] or None,
            make_default
        ))

        connection.commit()
        flash("Delivery address saved successfully.")

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("addresses"))


# ==================================================
# 23. SET DEFAULT DELIVERY ADDRESS
# ==================================================

@app.route("/addresses/default/<int:address_id>", methods=["POST"])
@customer_required
def set_default_address(address_id):

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE customer_addresses
            SET is_default = FALSE
            WHERE user_id = %s
        """, (session["user_id"],))

        cursor.execute("""
            UPDATE customer_addresses
            SET is_default = TRUE
            WHERE address_id = %s AND user_id = %s
        """, (address_id, session["user_id"]))

        if cursor.rowcount == 0:
            connection.rollback()
            flash("Address not found.")
        else:
            connection.commit()
            flash("Default address updated.")

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("addresses"))


# ==================================================
# 24. DELETE DELIVERY ADDRESS
# ==================================================

@app.route("/addresses/delete/<int:address_id>", methods=["POST"])
@customer_required
def delete_address(address_id):

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            DELETE FROM customer_addresses
            WHERE address_id = %s AND user_id = %s
        """, (address_id, session["user_id"]))

        if cursor.rowcount:
            connection.commit()
            flash("Address deleted successfully.")
        else:
            connection.rollback()
            flash("Address not found.")

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("addresses"))


# ==================================================
# 25. CHECKOUT
# ==================================================

@app.route("/checkout")
@customer_required
def checkout():

    cart_data = get_safe_cart()

    if not cart_data:
        flash("Your cart is empty.")
        return redirect(url_for("cart"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT *
            FROM customer_addresses
            WHERE user_id = %s
            ORDER BY is_default DESC, created_at DESC
        """, (session["user_id"],))

        saved_addresses = cursor.fetchall()

        if not saved_addresses:
            flash("Please add a delivery address first.")
            return redirect(url_for("addresses"))

        cart_items = []
        total = Decimal("0.00")

        for item in cart_data.values():

            if not isinstance(item, dict):
                continue

            try:
                product_id = int(item["product_id"])
                quantity = int(item["quantity"])
                size = item["size"]
            except (KeyError, ValueError, TypeError):
                continue

            if quantity <= 0 or size not in ALL_SIZES:
                continue

            cursor.execute("""
                SELECT
                    p.product_id,
                    p.product_name,
                    p.price,
                    p.is_active,
                    ps.stock
                FROM products p
                JOIN product_sizes ps
                    ON ps.product_id = p.product_id
                WHERE p.product_id = %s
                  AND ps.size = %s
            """, (product_id, size))

            product = cursor.fetchone()

            if not product or not product["is_active"]:
                continue

            if quantity > product["stock"]:
                flash(
                    f"Only {product['stock']} units of "
                    f"{product['product_name']} ({size}) are available."
                )
                return redirect(url_for("cart"))

            price = Decimal(str(product["price"]))
            line_total = price * quantity
            total += line_total

            cart_items.append({
                "product_id": product_id,
                "product_name": product["product_name"],
                "size": size,
                "quantity": quantity,
                "price": price,
                "line_total": line_total
            })

        if not cart_items:
            flash("Your cart has no available products.")
            return redirect(url_for("cart"))

        return render_template(
            "checkout.html",
            addresses=saved_addresses,
            cart_items=cart_items,
            total=total
        )

    finally:
        cursor.close()
        connection.close()


# ==================================================
# 26. PLACE CUSTOMER ORDER
# ==================================================

@app.route("/place-order", methods=["POST"])
@customer_required
def place_order():

    try:
        address_id = int(request.form.get("address_id", ""))
    except (ValueError, TypeError):
        flash("Please select a valid delivery address.")
        return redirect(url_for("checkout"))

    payment_method = request.form.get("payment_method", "COD")

    # Online payment is not active yet.
    if payment_method != "COD":
        flash("Only Cash on Delivery is currently available.")
        return redirect(url_for("checkout"))

    cart_data = get_safe_cart()

    if not cart_data:
        flash("Your cart is empty.")
        return redirect(url_for("cart"))

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        connection.start_transaction()

        # Verify the address belongs to this customer.
        cursor.execute("""
            SELECT *
            FROM customer_addresses
            WHERE address_id = %s AND user_id = %s
            FOR UPDATE
        """, (address_id, session["user_id"]))

        address = cursor.fetchone()

        if not address:
            connection.rollback()
            flash("Please select a valid delivery address.")
            return redirect(url_for("checkout"))

        order_items = []
        total = Decimal("0.00")

        # Lock inventory rows while placing the order.
        for item in cart_data.values():

            if not isinstance(item, dict):
                raise ValueError("Invalid cart item.")

            product_id = int(item["product_id"])
            quantity = int(item["quantity"])
            size = item["size"]

            if quantity <= 0 or size not in ALL_SIZES:
                raise ValueError("Invalid product quantity or size.")

            cursor.execute("""
                SELECT
                    p.product_id,
                    p.product_name,
                    p.price,
                    p.is_active,
                    ps.stock
                FROM products p
                JOIN product_sizes ps
                    ON ps.product_id = p.product_id
                WHERE p.product_id = %s
                  AND ps.size = %s
                FOR UPDATE
            """, (product_id, size))

            product = cursor.fetchone()

            if not product or not product["is_active"]:
                raise ValueError(
                    "A product in your cart is no longer available."
                )

            if product["stock"] < quantity:
                raise ValueError(
                    f"Insufficient stock for {product['product_name']} "
                    f"({size}). Available: {product['stock']}."
                )

            price = Decimal(str(product["price"]))
            total += price * quantity

            order_items.append({
                "product_id": product_id,
                "product_name": product["product_name"],
                "size": size,
                "quantity": quantity,
                "price": price
            })

        if not order_items:
            raise ValueError("Your cart has no valid products.")

        # Save delivery address as an order snapshot.
        cursor.execute("""
            INSERT INTO orders (
                user_id,
                total_amount,
                status,
                delivery_full_name,
                delivery_phone,
                delivery_address_line,
                delivery_city,
                delivery_state,
                delivery_pincode,
                delivery_landmark,
                payment_method,
                payment_status
            )
            VALUES (
                %s, %s, 'Pending',
                %s, %s, %s, %s, %s, %s, %s,
                'COD', 'Unpaid'
            )
        """, (
            session["user_id"],
            total,
            address["full_name"],
            address["phone"],
            address["address_line"],
            address["city"],
            address["state"],
            address["pincode"],
            address["landmark"]
        ))

        order_id = cursor.lastrowid

        for item in order_items:

            cursor.execute("""
                INSERT INTO order_items (
                    order_id,
                    product_id,
                    quantity,
                    size,
                    price_at_purchase
                )
                VALUES (%s, %s, %s, %s, %s)
            """, (
                order_id,
                item["product_id"],
                item["quantity"],
                item["size"],
                item["price"]
            ))

            cursor.execute("""
                UPDATE product_sizes
                SET stock = stock - %s
                WHERE product_id = %s
                  AND size = %s
                  AND stock >= %s
            """, (
                item["quantity"],
                item["product_id"],
                item["size"],
                item["quantity"]
            ))

            if cursor.rowcount != 1:
                raise ValueError(
                    "Stock changed while placing your order. Please try again."
                )

            sync_total_stock(cursor, item["product_id"])

        connection.commit()

        session["cart"] = {}
        session.modified = True

        flash(f"Order #{order_id} placed successfully!")
        return redirect(url_for("my_orders"))

    except ValueError as error:
        connection.rollback()
        flash(str(error))
        return redirect(url_for("checkout"))

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


# ==================================================
# 27. CUSTOMER ORDER HISTORY
# ==================================================

@app.route("/my-orders")
@customer_required
def my_orders():

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT *
            FROM orders
            WHERE user_id = %s
            ORDER BY order_date DESC
        """, (session["user_id"],))

        orders = cursor.fetchall()

        for order in orders:
            cursor.execute("""
                SELECT
                    oi.product_id,
                    oi.quantity,
                    oi.size,
                    oi.price_at_purchase,
                    p.product_name
                FROM order_items oi
                LEFT JOIN products p
                    ON p.product_id = oi.product_id
                WHERE oi.order_id = %s
            """, (order["order_id"],))

            order["items"] = cursor.fetchall()

        return render_template(
            "my_orders.html",
            orders=orders
        )

    finally:
        cursor.close()
        connection.close()


# ==================================================
# 28. ADMIN ORDER MANAGEMENT
# ==================================================

@app.route("/admin/orders")
@admin_required
def admin_orders():

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT
                o.*,
                u.full_name,
                u.email
            FROM orders o
            JOIN users u ON u.user_id = o.user_id
            ORDER BY o.order_date DESC
        """)

        orders = cursor.fetchall()

        for order in orders:

            order["address"] = {
                "full_name": order["delivery_full_name"],
                "phone": order["delivery_phone"],
                "address_line": order["delivery_address_line"],
                "city": order["delivery_city"],
                "state": order["delivery_state"],
                "pincode": order["delivery_pincode"],
                "landmark": order["delivery_landmark"]
            }

            cursor.execute("""
                SELECT
                    oi.product_id,
                    oi.quantity,
                    oi.size,
                    oi.price_at_purchase,
                    p.product_name
                FROM order_items oi
                LEFT JOIN products p
                    ON p.product_id = oi.product_id
                WHERE oi.order_id = %s
            """, (order["order_id"],))

            order["items"] = cursor.fetchall()

        return render_template(
            "admin_orders.html",
            orders=orders
        )

    finally:
        cursor.close()
        connection.close()


# ==================================================
# 29. UPDATE ORDER STATUS
# ==================================================

@app.route(
    "/admin/update-order-status/<int:order_id>",
    methods=["POST"]
)
@admin_required
def update_order_status(order_id):

    allowed_statuses = {
        "Pending",
        "Processing",
        "Shipped",
        "Delivered",
        "Cancelled"
    }

    new_status = request.form.get("status", "").strip()

    if new_status not in allowed_statuses:
        flash("Invalid order status.")
        return redirect(url_for("admin_orders"))

    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE orders
            SET status = %s
            WHERE order_id = %s
        """, (new_status, order_id))

        if cursor.rowcount:
            connection.commit()
            flash("Order status updated successfully.")
        else:
            connection.rollback()
            flash("Order not found.")

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    return redirect(url_for("admin_orders"))

# ==================================================
# 23. IMAGE SIZE ERROR
# ==================================================

@app.errorhandler(413)
def file_too_large(error):

    return (
        "Image is too large. Maximum file size is 5 MB.",
        413
    )


# ==================================================
# 24. RUN APPLICATION
# ==================================================

if __name__ == "__main__":

    app.run(debug=True)