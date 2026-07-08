import os
import json
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
import sass

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fridge.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


def compile_scss():
    """Компилирует SCSS в CSS при старте приложения."""
    scss_path = os.path.join(app.static_folder, 'scss', 'style.scss')
    css_path = os.path.join(app.static_folder, 'css', 'style.css')
    try:
        os.makedirs(os.path.dirname(css_path), exist_ok=True)
        with open(scss_path, 'r', encoding='utf-8') as f:
            scss_content = f.read()
        css_content = sass.compile(string=scss_content, output_style='compressed')
        with open(css_path, 'w', encoding='utf-8') as out:
            out.write(css_content)
        print("✅ SCSS скомпилирован в CSS")
    except Exception as e:
        print(f"⚠️ Ошибка компиляции SCSS: {e}")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=1.0)
    unit = db.Column(db.String(20), nullable=False, default='шт')
    category = db.Column(db.String(50), nullable=True)
    manufacture_date = db.Column(db.Date, nullable=True)
    expiration_date = db.Column(db.Date, nullable=True)
    
    # Новые поля для КБЖУ
    calories = db.Column(db.Integer, nullable=True, default=0)
    proteins = db.Column(db.Float, nullable=True, default=0.0)
    fats = db.Column(db.Float, nullable=True, default=0.0)
    carbs = db.Column(db.Float, nullable=True, default=0.0)

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
        self.category = form_data.get('category') or 'Разное'
        
        # КБЖУ
        self.calories = int(form_data.get('calories') or 0)
        self.proteins = float(form_data.get('proteins') or 0.0)
        self.fats = float(form_data.get('fats') or 0.0)
        self.carbs = float(form_data.get('carbs') or 0.0)

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
    query = request.args.get('q', '').strip().lower()
    if not query or len(query) < 2:
        return jsonify([])

    results = []
    seen_names = set()

    # Поиск по JSON-справочнику
    try:
        if os.path.exists('food_db.json'):
            with open('food_db.json', 'r', encoding='utf-8') as f:
                static_db = json.load(f)
                
            for item in static_db:
                name = item.get('name', '')
                if query in name.lower():
                    name_lower = name.strip().lower()
                    if name_lower not in seen_names:
                        seen_names.add(name_lower)
                        results.append({
                            'name': name,
                            'category': item.get('category', 'Разное'),
                            'calories': item.get('calories', 0),
                            'proteins': item.get('proteins', 0.0),
                            'fats': item.get('fats', 0.0),
                            'carbs': item.get('carbs', 0.0)
                        })
    except Exception as e:
        print(f"Ошибка JSON-базы: {e}")

    return jsonify(results[:6])


@app.route('/consume/<int:product_id>', methods=['POST'])
def consume_product(product_id):
    product = Product.query.get_or_404(product_id)
    try:
        amount = float(request.form.get('amount', 1))
    except ValueError:
        return redirect(url_for('index'))

    if amount >= product.quantity:
        db.session.delete(product)
        flash(f'🗑️ Продукт "{product.name}" полностью использован', 'info')
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