# auth.py — Autenticação de usuários (cadastro, login, logout)

from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db
import re

# Blueprint permite separar as rotas de autenticação do app.py principal
auth = Blueprint('auth', __name__)


@auth.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    """GET: exibe o formulário. POST: valida e cria o usuário no banco."""
    erro = ''
    if request.method == 'POST':
        nome  = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        if not nome or not email or not senha:
            erro = 'Preencha todos os campos.'
        elif not re.match(r'^[\w.+-]+@[\w-]+\.\w+$', email):
            erro = 'Email inválido. Use o formato: nome@dominio.com'
        elif len(senha) < 6:
            erro = 'A senha deve ter pelo menos 6 caracteres.'
        else:
            # Nunca salva senha em texto puro — gera hash criptográfico
            senha_hash = generate_password_hash(senha)
            db = get_db()
            try:
                db.execute(
                    'INSERT INTO users (nome, email, senha) VALUES (?, ?, ?)',
                    (nome, email, senha_hash)
                )
                db.commit()
                return redirect(url_for('auth.login'))
            except Exception:
                # UNIQUE no email gera exceção se já cadastrado
                erro = 'Este email já está cadastrado.'
            finally:
                db.close()

    return render_template('cadastro.html', erro=erro)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    """GET: exibe o formulário. POST: verifica credenciais e inicia sessão."""
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
            # session persiste entre requisições via cookie criptografado
            session.clear()
            session['user_id']   = usuario['id']
            session['user_nome'] = usuario['nome']
            return redirect(url_for('home'))
        else:
            erro = 'Email ou senha incorretos.'

    return render_template('login.html', erro=erro)


@auth.route('/logout')
def logout():
    """Apaga a sessão e redireciona para o login."""
    session.clear()
    return redirect(url_for('auth.login'))
