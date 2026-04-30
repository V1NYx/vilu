from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db

# Blueprint = módulo separado de rotas que o app.py vai registrar
# Assim o código de autenticação fica isolado do código de recomendação
auth = Blueprint('auth', __name__)


# ── CADASTRO ──────────────────────────────────────────────────────────────────
@auth.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    """
    GET  → exibe o formulário de cadastro
    POST → processa os dados e cria o usuário no banco
    """
    erro = ''
    if request.method == 'POST':
        nome  = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        # Validações básicas
        if not nome or not email or not senha:
            erro = 'Preencha todos os campos.'
        elif len(senha) < 6:
            erro = 'A senha deve ter pelo menos 6 caracteres.'
        else:
            # generate_password_hash transforma "minhasenha" em algo como
            # "pbkdf2:sha256:260000$xK3..." — nunca salve senha em texto puro!
            senha_hash = generate_password_hash(senha)

            db = get_db()
            try:
                db.execute(
                    'INSERT INTO users (nome, email, senha) VALUES (?, ?, ?)',
                    (nome, email, senha_hash)
                )
                db.commit()
                # Redireciona para login após cadastro bem-sucedido
                return redirect(url_for('auth.login'))

            except Exception:
                # O UNIQUE no email dispara exceção se já estiver cadastrado
                erro = 'Este email já está cadastrado. Tente fazer login.'
            finally:
                db.close()

    return render_template('cadastro.html', erro=erro)


# ── LOGIN ─────────────────────────────────────────────────────────────────────
@auth.route('/login', methods=['GET', 'POST'])
def login():
    """
    GET  → exibe o formulário de login
    POST → verifica credenciais e inicia a sessão
    """
    erro = ''
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        db = get_db()
        # fetchone() retorna a primeira linha encontrada, ou None se não achar
        usuario = db.execute(
            'SELECT * FROM users WHERE email = ?', (email,)
        ).fetchone()
        db.close()

        # check_password_hash compara a senha digitada com o hash salvo
        if usuario and check_password_hash(usuario['senha'], senha):
            # session é um dicionário que persiste entre requisições via cookie
            session.clear()
            session['user_id']   = usuario['id']
            session['user_nome'] = usuario['nome']
            return redirect(url_for('home'))
        else:
            erro = 'Email ou senha incorretos.'

    return render_template('login.html', erro=erro)


# ── LOGOUT ────────────────────────────────────────────────────────────────────
@auth.route('/logout')
def logout():
    """Limpa a sessão e redireciona para o login."""
    session.clear()
    return redirect(url_for('auth.login'))
