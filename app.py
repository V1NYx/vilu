"""
app.py — Servidor principal do VILU

Mudanças desta versão:
  - /comentar agora herda automaticamente a avaliação já salva pelo usuário.
    Se não tiver avaliado, publica sem nota. Sem estrelas no formulário de comentário.
  - Curtidas removidas do feed (simplificação solicitada)
  - import pandas removido (não era usado diretamente aqui)
"""

from flask import Flask, render_template, request, redirect, url_for, session
from functools import wraps
import requests
import re

from database import get_db, criar_tabelas
from auth import auth as auth_blueprint
from sistema_xai import recomendar_hibrido, filmes, dados_completos

# ── CONFIGURAÇÃO ──────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = 'vilu-chave-secreta-troque-em-producao-2024'
app.register_blueprint(auth_blueprint)
criar_tabelas()

TMDB_API_KEY = '417fbe5b98d6a5a1daff00dfc9a77915'

# Cache simples em memória para resultados TMDB
# Evita chamar a API toda vez que a mesma página é acessada
_cache_tmdb = {}


# ── DECORATOR ────────────────────────────────────────────────────────────────

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


# ── TMDB ─────────────────────────────────────────────────────────────────────

def buscar_info_tmdb(titulo_movielens):
    """
    Busca sinopse e pôster no TMDB.
    Usa cache em memória: na segunda chamada com o mesmo título,
    retorna instantaneamente sem fazer requisição HTTP.
    """
    if titulo_movielens in _cache_tmdb:
        return _cache_tmdb[titulo_movielens]

    titulo_limpo = re.sub(r'\s*\(\d{4}\)', '', titulo_movielens).strip()
    url    = 'https://api.themoviedb.org/3/search/movie'
    params = {'api_key': TMDB_API_KEY, 'query': titulo_limpo, 'language': 'pt-BR'}

    try:
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 401:
            result = ('Chave da API TMDB inválida.', None)
        else:
            dados      = resp.json()
            resultados = dados.get('results', [])
            if resultados:
                f          = resultados[0]
                sinopse    = f.get('overview') or 'Sinopse não disponível em português.'
                poster_path = f.get('poster_path')
                poster_url  = f'https://image.tmdb.org/t/p/w500{poster_path}' if poster_path else None
                result = (sinopse, poster_url)
            else:
                result = ('Sinopse não disponível.', None)
    except requests.exceptions.Timeout:
        result = ('Tempo de conexão esgotado.', None)
    except Exception as e:
        print(f'Erro TMDB: {e}')
        result = ('Sinopse não disponível.', None)

    _cache_tmdb[titulo_movielens] = result
    return result


# ── HOME ──────────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    recomendacoes    = []
    explicacao       = ''
    filme_escolhido  = ''
    poster_principal = None
    modo             = ''
    erro             = ''

    if request.method == 'POST':
        nome_digitado = request.form.get('nome_filme', '').strip()
        user_id       = session.get('user_id')

        titulo_completo, recomendacoes, explicacao, modo, erro = \
            recomendar_hibrido(nome_digitado, user_id)

        if titulo_completo:
            filme_escolhido     = titulo_completo
            _, poster_principal = buscar_info_tmdb(titulo_completo)

    return render_template(
        'index.html',
        filme_escolhido     = filme_escolhido,
        lista_recomendacoes = recomendacoes,
        explicacao          = explicacao,
        modo                = modo,
        erro                = erro,
        poster_principal    = poster_principal,
        user_nome           = session.get('user_nome', '')
    )


# ── DETALHES ─────────────────────────────────────────────────────────────────

@app.route('/detalhes/<path:nome_filme>')
@login_required
def detalhes(nome_filme):
    busca = filmes[filmes['title'] == nome_filme]
    if len(busca) == 0:
        return render_template('404.html', mensagem='Filme não encontrado.'), 404

    dados_filme   = busca.iloc[0]
    movie_id      = int(dados_filme['movieId'])
    generos_lista = dados_filme['genres'].split('|')

    nota_media = '-'
    if nome_filme in dados_completos['title'].values:
        media      = dados_completos[dados_completos['title'] == nome_filme]['rating'].mean()
        nota_media = f'{media:.2f}'

    user_id      = session.get('user_id')
    nota_usuario = None
    db = get_db()

    row = db.execute(
        'SELECT nota FROM avaliacoes WHERE user_id = ? AND movie_id = ?',
        (user_id, movie_id)
    ).fetchone()
    if row:
        nota_usuario = row['nota']

    # Comentários sem curtidas (simplificado)
    comentarios = db.execute("""
        SELECT c.id, c.comentario, c.nota, c.data,
               u.nome AS autor, u.id AS autor_id
        FROM comentarios c
        JOIN users u ON c.user_id = u.id
        WHERE c.movie_id = ?
        ORDER BY c.data DESC
    """, (movie_id,)).fetchall()

    db.close()

    sinopse, poster_url = buscar_info_tmdb(nome_filme)

    return render_template(
        'detalhes.html',
        titulo       = nome_filme,
        movie_id     = movie_id,
        generos      = generos_lista,
        nota_media   = nota_media,
        sinopse      = sinopse,
        poster_url   = poster_url,
        nota_usuario = nota_usuario,
        comentarios  = comentarios,
        user_nome    = session.get('user_nome', ''),
        user_id      = user_id
    )


# ── AVALIAR ───────────────────────────────────────────────────────────────────

@app.route('/avaliar', methods=['POST'])
@login_required
def avaliar():
    movie_id = request.form.get('movie_id')
    titulo   = request.form.get('titulo')
    nota     = float(request.form.get('nota', 0))
    user_id  = session['user_id']

    if not movie_id or not titulo or nota < 0.5:
        return redirect(url_for('home'))

    db = get_db()
    db.execute("""
        INSERT INTO avaliacoes (user_id, movie_id, titulo, nota)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, movie_id) DO UPDATE SET
            nota = excluded.nota,
            data = CURRENT_TIMESTAMP
    """, (user_id, movie_id, titulo, nota))
    db.commit()
    db.close()

    return redirect(url_for('detalhes', nome_filme=titulo))


# ── COMENTAR ─────────────────────────────────────────────────────────────────

@app.route('/comentar', methods=['POST'])
@login_required
def comentar():
    """
    MUDANÇA: a nota do comentário é herdada automaticamente da avaliação
    privada do usuário (tabela avaliacoes). Se não avaliou, publica sem nota.
    O formulário de comentário não tem mais campo de estrelas.
    """
    movie_id   = request.form.get('movie_id')
    titulo     = request.form.get('titulo')
    comentario = request.form.get('comentario', '').strip()
    user_id    = session['user_id']

    if not comentario or len(comentario) < 3 or len(comentario) > 500:
        return redirect(url_for('detalhes', nome_filme=titulo))

    # Busca a avaliação privada do usuário para herdar a nota
    db = get_db()
    row = db.execute(
        'SELECT nota FROM avaliacoes WHERE user_id = ? AND movie_id = ?',
        (user_id, movie_id)
    ).fetchone()
    nota_herdada = row['nota'] if row else None

    db.execute("""
        INSERT INTO comentarios (user_id, movie_id, titulo, nota, comentario)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, movie_id, titulo, nota_herdada, comentario))
    db.commit()
    db.close()

    return redirect(url_for('detalhes', nome_filme=titulo))


# ── EXCLUIR COMENTÁRIO ────────────────────────────────────────────────────────

@app.route('/excluir_comentario/<int:comentario_id>', methods=['POST'])
@login_required
def excluir_comentario(comentario_id):
    user_id = session['user_id']
    db = get_db()

    com = db.execute(
        'SELECT titulo, user_id FROM comentarios WHERE id = ?',
        (comentario_id,)
    ).fetchone()

    if com and com['user_id'] == user_id:
        db.execute('DELETE FROM comentarios WHERE id = ?', (comentario_id,))
        db.commit()
        titulo = com['titulo']
    else:
        titulo = ''

    db.close()
    return redirect(url_for('detalhes', nome_filme=titulo) if titulo else url_for('feed'))


# ── FEED ──────────────────────────────────────────────────────────────────────

@app.route('/feed')
@login_required
def feed():
    db = get_db()
    posts = db.execute("""
        SELECT c.id, c.comentario, c.nota, c.titulo, c.movie_id, c.data,
               u.nome AS autor, u.id AS autor_id
        FROM comentarios c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.data DESC
        LIMIT 100
    """).fetchall()
    db.close()

    return render_template(
        'feed.html',
        posts     = posts,
        user_nome = session.get('user_nome', ''),
        user_id   = session['user_id']
    )


# ── PERFIL ────────────────────────────────────────────────────────────────────

@app.route('/perfil')
@login_required
def perfil():
    user_id = session['user_id']
    db = get_db()

    avaliacoes = db.execute("""
        SELECT titulo, movie_id, nota, data
        FROM avaliacoes
        WHERE user_id = ?
        ORDER BY data DESC
    """, (user_id,)).fetchall()

    comentarios = db.execute("""
        SELECT c.id, c.titulo, c.nota, c.comentario, c.data
        FROM comentarios c
        WHERE c.user_id = ?
        ORDER BY c.data DESC
    """, (user_id,)).fetchall()

    db.close()

    return render_template(
        'perfil.html',
        avaliacoes  = avaliacoes,
        comentarios = comentarios,
        user_nome   = session.get('user_nome', ''),
        user_id     = user_id
    )


# ── PERFIL PÚBLICO ────────────────────────────────────────────────────────────

@app.route('/usuario/<int:uid>')
@login_required
def usuario_publico(uid):
    db = get_db()
    usuario = db.execute(
        'SELECT id, nome, criado_em FROM users WHERE id = ?', (uid,)
    ).fetchone()

    if not usuario:
        return render_template('404.html', mensagem='Usuário não encontrado.'), 404

    comentarios = db.execute("""
        SELECT c.id, c.titulo, c.nota, c.comentario, c.data
        FROM comentarios c
        WHERE c.user_id = ?
        ORDER BY c.data DESC
    """, (uid,)).fetchall()

    db.close()

    return render_template(
        'usuario_publico.html',
        usuario     = usuario,
        comentarios = comentarios,
        user_nome   = session.get('user_nome', ''),
        user_id     = session['user_id']
    )


# ── ERRO 404 ──────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def pagina_nao_encontrada(e):
    return render_template('404.html', mensagem='Página não encontrada.'), 404


if __name__ == '__main__':
    app.run(debug=True)
