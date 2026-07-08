import os
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash
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

    if not os.path.exists(css_path) or os.path.getmtime(scss_path) > os.path.getmtime(css_path):
        os.makedirs(os.path.dirname(css_path), exist_ok=True)
        with open(scss_path, 'r', encoding='utf-8') as f:
            scss_content = f.read()
        css_content = sass.compile(string=scss_content, output_style='compressed')
        with open(css_path, 'w', encoding='utf-8') as out:
            out.write(css_content)
        print("✅ SCSS скомпилирован в CSS")


with app.app_context():
    compile_scss()
    db.create_all()


# ============================================================
# МОДЕЛЬ
# ============================================================
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Float, nullable=False, default=1.0)
    unit = db.Column(db.String(20), nullable=False, default='шт')
    expiration_date = db.Column(db.Date, nullable=True)
    manufacture_date = db.Column(db.Date, nullable=True)
    category = db.Column(db.String(50), nullable=True)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_expired(self) -> bool:
        """Проверяет, просрочен ли продукт."""
        if not self.expiration_date:
            return False
        return self.expiration_date < date.today()

    @property
    def days_left(self) -> int | None:
        """Возвращает количество дней до истечения срока годности."""
        if not self.expiration_date:
            return None
        return (self.expiration_date - date.today()).days

    @property
    def expiry_status(self) -> dict:
        """Возвращает статус срока годности: цвет, класс, текст."""
        days = self.days_left
        if days is None:
            return {'color': 'secondary', 'class': 'secondary', 'text': 'Не указан'}
        if days < 0:
            return {'color': 'danger', 'class': 'danger', 'text': f'Просрочен на {-days} дн.'}
        if days == 0:
            return {'color': 'warning', 'class': 'warning', 'text': 'Сегодня'}
        if days <= 3:
            return {'color': 'warning', 'class': 'warning', 'text': f'{days} дн.'}
        return {'color': 'success', 'class': 'success', 'text': f'{days} дн.'}

    @property
    def expiry_bar_width(self) -> int:
        """Ширина прогресс-бара (от 0 до 100%)."""
        days = self.days_left
        if days is None:
            return 0
        if days < 0:
            return 100
        if days > 30:
            return 100
        return int((days / 30) * 100)

    @classmethod
    def from_form(cls, form_data):
        """Создаёт продукт из данных формы с валидацией."""
        name = form_data.get('name', '').strip()
        if not name:
            raise ValueError('Название продукта обязательно')

        try:
            quantity = float(form_data.get('quantity', 1.0))
        except ValueError:
            raise ValueError('Количество должно быть числом')

        if quantity <= 0:
            raise ValueError('Количество должно быть положительным')

        unit = form_data.get('unit', 'шт')
        category = form_data.get('category', 'Без категории').strip() or 'Без категории'

        # Обработка дат
        manufacture_date = cls._parse_date(form_data.get('manufacture_date'))
        expiration_type = form_data.get('expiration_type', 'date')
        expiration_date = None

        if expiration_type == 'date':
            expiration_date = cls._parse_date(form_data.get('expiration_date'))
            if not expiration_date:
                raise ValueError('Укажите дату годности')
        elif expiration_type == 'from_manufacture':
            days_str = form_data.get('expiration_days', '').strip()
            if not days_str:
                raise ValueError('Укажите количество дней хранения')
            try:
                days = int(days_str)
            except ValueError:
                raise ValueError('Количество дней должно быть целым числом')
            if days <= 0:
                raise ValueError('Количество дней должно быть положительным')
            if not manufacture_date:
                raise ValueError('Для расчёта от даты изготовления укажите дату изготовления')
            expiration_date = manufacture_date + timedelta(days=days)

        return cls(
            name=name,
            quantity=quantity,
            unit=unit,
            category=category,
            manufacture_date=manufacture_date,
            expiration_date=expiration_date
        )

    @staticmethod
    def _parse_date(date_str: str) -> date | None:
        """Парсит строку в дату или возвращает None."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return None

    def update_from_form(self, form_data):
        """Обновляет продукт из данных формы."""
        self.name = form_data.get('name', '').strip()
        if not self.name:
            raise ValueError('Название продукта обязательно')

        try:
            self.quantity = float(form_data.get('quantity', 1.0))
        except ValueError:
            raise ValueError('Количество должно быть числом')

        if self.quantity <= 0:
            raise ValueError('Количество должно быть положительным')

        self.unit = form_data.get('unit', 'шт')
        self.category = form_data.get('category', 'Без категории').strip() or 'Без категории'

        self.manufacture_date = self._parse_date(form_data.get('manufacture_date'))

        expiration_type = form_data.get('expiration_type', 'date')
        if expiration_type == 'date':
            self.expiration_date = self._parse_date(form_data.get('expiration_date'))
            if not self.expiration_date:
                raise ValueError('Укажите дату годности')
        elif expiration_type == 'from_manufacture':
            days_str = form_data.get('expiration_days', '').strip()
            if not days_str:
                raise ValueError('Укажите количество дней хранения')
            try:
                days = int(days_str)
            except ValueError:
                raise ValueError('Количество дней должно быть целым числом')
            if days <= 0:
                raise ValueError('Количество дней должно быть положительным')
            if not self.manufacture_date:
                raise ValueError('Для расчёта от даты изготовления укажите дату изготовления')
            self.expiration_date = self.manufacture_date + timedelta(days=days)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
def get_alerts(products):
    """Собирает предупреждения о просроченных и скоро истекающих продуктах."""
    today = date.today()
    expired = []
    warning = []

    for p in products:
        if not p.expiration_date:
            continue
        days = (p.expiration_date - today).days
        if days < 0:
            expired.append(p)
        elif 0 <= days <= 3:
            warning.append((p, days))

    return expired, warning


def flash_errors(form_errors):
    """Выводит все ошибки формы как flash-сообщения."""
    for error in form_errors:
        flash(error, 'danger')


# ============================================================
# МАРШРУТЫ
# ============================================================
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            product = Product.from_form(request.form)
            db.session.add(product)
            db.session.commit()
            flash(f'✅ Продукт "{product.name}" добавлен!', 'success')
        except ValueError as e:
            flash(str(e), 'danger')
        return redirect(url_for('index'))

    products = Product.query.order_by(Product.date_added.desc()).all()
    expired, warning = get_alerts(products)

    return render_template(
        'index.html',
        products=products,
        expired_products=expired,
        warning_products=warning
    )


@app.route('/use/<int:product_id>', methods=['POST'])
def use_product(product_id):
    product = Product.query.get_or_404(product_id)

    try:
        amount = float(request.form.get('use_amount', 1.0))
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
            flash(f'✅ Продукт "{product.name}" обновлён!', 'success')
            return redirect(url_for('index'))
        except ValueError as e:
            flash(str(e), 'danger')

    return render_template('edit.html', product=product)


if __name__ == '__main__':
    app.run(debug=True)