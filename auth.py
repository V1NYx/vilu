from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db

auth = Blueprint('auth', __name__)


@auth.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    erro = ''
    if request.method == 'POST':
        nome  = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        if not nome or not email or not senha:
            erro = 'Preencha todos os campos.'
        else:
            db = get_db()
            try:
                db.execute(
                    'INSERT INTO users (nome, email, senha) VALUES (?, ?, ?)',
                    (nome, email, generate_password_hash(senha))
                )
                db.commit()
                return redirect(url_for('auth.login'))
            except Exception:
                erro = 'Este email já está cadastrado.'
            finally:
                db.close()

    return render_template('cadastro.html', erro=erro)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    erro = ''
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        db      = get_db()
        usuario = db.execute(
            'SELECT * FROM users WHERE email = ?', (email,)
        ).fetchone()
        db.close()

        if usuario and check_password_hash(usuario['senha'], senha):
            session.clear()
            session['user_id']   = usuario['id']
            session['user_nome'] = usuario['nome']
            return redirect(url_for('home'))

        erro = 'Email ou senha incorretos.'

    return render_template('login.html', erro=erro)


@auth.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
