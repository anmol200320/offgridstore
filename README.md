# OFFGRID® — Streetwear E-Commerce Website

A full-stack streetwear e-commerce web application built with **HTML, CSS, JavaScript, Python (Flask), and MySQL**.

OFFGRID is a portfolio project designed around a modern streetwear shopping experience, with customer accounts, product browsing, shopping cart functionality, order management, and an administrative dashboard.

## 🚀 Features

### Customer Features
- Browse the available streetwear collection.
- View products and product details.
- Register and log in to customer accounts.
- Add products to the shopping cart.
- Update product quantities and remove items.
- Proceed through the checkout process.
- Manage saved delivery addresses.
- View order history and order details.

### Admin Features
- Secure admin login.
- Access an administrative dashboard.
- Add and manage products.
- Upload product images.
- Manage product categories.
- Manage product sizes and stock quantities.
- View and manage customer orders.

### Design
- Dark-themed OFFGRID® branding.
- Clean, modern streetwear-inspired interface.
- Responsive layouts.
- Beige background with a dark header and minimalist styling.

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| HTML5 | Website structure |
| CSS3 | Styling and layouts |
| JavaScript | Frontend interactions |
| Python | Backend programming |
| Flask | Web framework |
| MySQL | Relational database |
| mysql-connector-python | Database connectivity |
| python-dotenv | Environment variable management |
| Git & GitHub | Version control |

## 📁 Project Structure

```text
offgridstore/
│
├── app.py
├── admin.py
├── database.py
├── setup_secret.py
├── .env
├── .gitignore
│
├── static/
│   ├── css/
│   ├── js/
│   └── uploads/
│
└── templates/
    ├── home.html
    ├── shop.html
    ├── about.html
    ├── contact.html
    └── ...
```

*The structure above is an overview; additional template and static files are part of the project.*

## ⚙️ Installation & Setup

Follow these steps to run OFFGRID locally.

### 1. Clone the repository

```bash
git clone https://github.com/anmol200320/offgridstore.git
```

### 2. Navigate to the project folder

```bash
cd offgridstore
```

### 3. Create a virtual environment

```bash
python -m venv venv
```

Activate it on Windows:

```bash
venv\Scripts\activate
```

### 4. Install dependencies

```bash
pip install Flask mysql-connector-python python-dotenv
```

### 5. Configure environment variables

Create a `.env` file in the project root:

```env
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=offgrid_store
```

Replace the example values with your own MySQL credentials.

### 6. Set up the database

- Install and start MySQL.
- Create a database named `offgrid_store`.
- Set up the required tables for users, products, categories, orders, and order items.
- Configure the application to use your database credentials.

### 7. Run the application

```bash
python app.py
```

Open your browser and visit:

**http://127.0.0.1:5000**

## 🔐 Security

- Database credentials are stored in environment variables.
- The `.env` file should never be committed to GitHub.
- Database passwords and secret keys should never be shared publicly.
- Uploaded files and sensitive configuration should be handled securely.

## 🌐 Deployment

Deployment is currently in progress.

The planned deployment setup includes:
- Flask application hosting.
- Cloud-hosted MySQL database.
- Environment-based configuration.
- Public website URL.

## 🎯 Project Objective

The goal of OFFGRID was to gain practical experience in full-stack web development by building an e-commerce application from the ground up.

The project helped me explore:
- Frontend and backend integration.
- Database design and connectivity.
- User authentication.
- CRUD operations.
- Shopping cart functionality.
- Admin-side product and order management.
- Git and GitHub workflows.

## 👩‍💻 Developer

**Anmol Singh**

BCA Student | Aspiring Software Developer

- GitHub: [@anmol200320](https://github.com/anmol200320)

---

*OFFGRID® — Built as a learning and portfolio project.*
