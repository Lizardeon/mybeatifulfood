import os
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
import sass
import requests

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fridge.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


def compile_scss():
    """Компилирует SCSS в CSS при старте приложения."""
    scss_path = os.path.join(app.static_folder, 'scss', 'style.scss')
    css_path = os.path.join(app.static_folder, 'css', 'style.css')

    if not os.path.exists(css_path) or os.path.getmtime(scss_path) > os.path.getmtime(css_path):
        os.makedirs(os.path.dirname(css_path), exist_ok=True)
        with open(scss_path, 'r', encoding='utf-8') as f:
            scss_content = f.read()
        css_content = sass.compile(string=scss_content, output_style='compressed')
        with open(css_path, 'w', encoding='utf-8') as out:
            out.write(css_content)
        print("✅ SCSS скомпилирован в CSS")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=1.0)
    unit = db.Column(db.String(20), nullable=False, default='шт')
    category = db.Column(db.String(50), nullable=True)
    manufacture_date = db.Column(db.Date, nullable=True)
    expiration_date = db.Column(db.Date, nullable=True)

    @property
    def days_left(self):
        if self.expiration_date:
            delta = self.expiration_date - date.today()
            return delta.days
        return None

    def update_from_form(self, form_data):
        self.name = form_data.get('name')
        self.quantity = float(form_data.get('quantity') or 1.0)
        self.unit = form_data.get('unit', 'шт')
        self.category = form_data.get('category') or None

        m_date_str = form_data.get('manufacture_date')
        self.manufacture_date = datetime.strptime(m_date_str, '%Y-%m-%d').date() if m_date_str else None

        exp_type = form_data.get('expiration_type')
        if exp_type == 'date':
            exp_date_str = form_data.get('expiration_date')
            self.expiration_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date() if exp_date_str else None
        elif exp_type == 'from_manufacture' and self.manufacture_date:
            days = int(form_data.get('expiration_days') or 7)
            self.expiration_date = self.manufacture_date + timedelta(days=days)
        else:
            self.expiration_date = None


with app.app_context():
    compile_scss()
    db.create_all()


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            product = Product()
            product.update_from_form(request.form)
            db.session.add(product)
            db.session.commit()
            flash(f'✨ Продукт "{product.name}" успешно добавлен!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Ошибка при добавлении продукта: {e}', 'danger')
        return redirect(url_for('index'))

    products = Product.query.order_by(Product.expiration_date.asc().nullslast()).all()
    
    expired_products = [p for p in products if p.days_left is not None and p.days_left < 0]
    warning_products = [p for p in products if p.days_left is not None and 0 <= p.days_left <= 3]

    return render_template('index.html', 
                           products=products, 
                           expired_products=expired_products, 
                           warning_products=warning_products,
                           now=date.today())


@app.route('/api/search-food', methods=['GET'])
def search_food():
    """Эндпоинт для живого поиска продуктов по базе Open Food Facts."""
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify([])

    # Используем российское зеркало базы для более точных совпадений
    url = "https://ru.openfoodfacts.org/cgi/search.pl"
    params = {
        'search_terms': query,
        'search_simple': 1,
        'action': 'process',
        'json': 1,
        'page_size': 6
    }
    
    try:
        headers = {'User-Agent': 'SmartFridgeApp - Web - Version 1.0'}
        response = requests.get(url, params=params, headers=headers, timeout=4)
        if response.status_code == 200:
            data = response.json()
            products = data.get('products', [])
            
            results = []
            for p in products:
                name = p.get('product_name_ru') or p.get('product_name')
                if not name:
                    continue
                
                # Попробуем вытащить категорию на русском или отформатировать базовый тег
                category = 'Разное'
                categories = p.get('categories_tags', [])
                if categories:
                    category = categories[0].split(':')[-1].replace('-', ' ').capitalize()
                    # Небольшой маппинг для адекватных категорий
                    category_map = {
                        'Milks': 'Молочные продукты', 'Cheeses': 'Сыры', 'Beverages': 'Напитки',
                        'Groceries': 'Бакалея', 'Snacks': 'Снеки', 'Meats': 'Мясо', 'Yogurts': 'Йогурты'
                    }
                    category = category_map.get(category, category)

                results.append({
                    'name': name,
                    'category': category
                })
            return jsonify(results)
    except Exception as e:
        print(f"Ошибка при работе с внешним API: {e}")
        
    return jsonify([])


@app.route('/consume/<int:product_id>', methods=['POST'])
def consume_product(product_id):
    product = Product.query.get_or_404(product_id)
    try:
        amount = float(request.form.get('amount', 1))
    except ValueError:
        flash('Введите корректное количество для списания', 'danger')
        return redirect(url_for('index'))

    if amount <= 0:
        flash('Количество для списания должно быть положительным', 'danger')
        return redirect(url_for('index'))

    if amount >= product.quantity:
        db.session.delete(product)
        flash(f'🗑️ Продукт "{product.name}" полностью использован и удалён', 'info')
    else:
        product.quantity -= amount
        flash(f'📦 Списано {amount} {product.unit} продукта "{product.name}"', 'success')

    db.session.commit()
    return redirect(url_for('index'))


@app.route('/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash(f'🗑️ Продукт "{product.name}" удалён', 'info')
    return redirect(url_for('index'))


@app.route('/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)

    if request.method == 'POST':
        try:
            product.update_from_form(request.form)
            db.session.commit()
            flash(f'✏️ Продукт "{product.name}" обновлен', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f'❌ Ошибка при изменении: {e}', 'danger')

    return render_template('edit.html', product=product)


if __name__ == '__main__':
    app.run(debug=True)