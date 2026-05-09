import os
import re
import requests
from functools import wraps
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, render_template, request, redirect, url_for, session, jsonify

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_db, criar_tabelas
from auth import auth as auth_blueprint
from sistema_xai import (
    recomendar_hibrido, filmes, dados_completos,
    _generos_idx, buscar_historico_usuario,
    _historico_relevante, contagem_votos,
    atualizar_matriz
)

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'vilu-dev-key-2024')
app.register_blueprint(auth_blueprint)
criar_tabelas()

TMDB_KEY    = os.getenv('TMDB_API_KEY', '417fbe5b98d6a5a1daff00dfc9a77915')
_tmdb_cache = {}


def login_required(f):
    @wraps(f)
    def check(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return check


# ── TMDB ──────────────────────────────────────────────────────────────────────

def _tmdb_get(path, params=None, timeout=4):
    """Wrapper simples para chamadas à API do TMDB."""
    base = {'api_key': TMDB_KEY, 'language': 'pt-BR'}
    if params:
        base.update(params)
    try:
        return requests.get(f'https://api.themoviedb.org/3{path}', params=base, timeout=timeout).json()
    except Exception:
        return {}


def buscar_info_tmdb(titulo_movielens):
    if titulo_movielens in _tmdb_cache:
        return _tmdb_cache[titulo_movielens]

    # Limpa o título antes de buscar: remove ano, a.k.a., e inverte "Matrix, The"
    t = re.sub(r'\s*\(\d{4}\)', '', titulo_movielens).strip()
    t = re.sub(r'\s*\(a\.k\.a\..*?\)', '', t, flags=re.IGNORECASE).strip()
    if ', The' in t:
        t = 'The ' + t.replace(', The', '')
    elif ', A ' in t:
        t = 'A ' + t.replace(', A ', ' ')

    dados = _tmdb_get('/search/movie', {'query': t})
    resultados = dados.get('results', [])

    if not resultados:
        result = ('Sinopse não disponível.', None, None, [], None, [], [])
        _tmdb_cache[titulo_movielens] = result
        return result

    item  = resultados[0]
    mid   = item.get('id')
    thumb = item.get('poster_path')

    sinopse    = item.get('overview') or 'Sinopse não disponível em português.'
    poster_url = f'https://image.tmdb.org/t/p/w500{thumb}' if thumb else None
    titulo_ptbr = item.get('title')

    # Streamings disponíveis no Brasil
    streamings = []
    if mid:
        wp = _tmdb_get(f'/movie/{mid}/watch/providers', {})
        for p in wp.get('results', {}).get('BR', {}).get('flatrate', []):
            streamings.append({
                'nome': p.get('provider_name'),
                'logo': f"https://image.tmdb.org/t/p/original{p.get('logo_path')}"
            })

    # Trailer — tenta PT-BR primeiro, cai para EN
    trailer_key = None
    if mid:
        for lang in ['pt-BR', 'en-US']:
            videos = _tmdb_get(f'/movie/{mid}/videos', {'language': lang}).get('results', [])
            for tipo in ['Trailer', 'Teaser']:
                match = next((v for v in videos if v.get('site') == 'YouTube' and v.get('type') == tipo), None)
                if match:
                    trailer_key = match['key']
                    break
            if trailer_key:
                break

    # Elenco e direção
    elenco, diretores = [], []
    if mid:
        creditos = _tmdb_get(f'/movie/{mid}/credits')
        for ator in creditos.get('cast', [])[:7]:
            foto = ator.get('profile_path')
            elenco.append({
                'nome':       ator.get('name'),
                'personagem': ator.get('character'),
                'foto':       f'https://image.tmdb.org/t/p/w185{foto}' if foto else None
            })
        diretores = [
            {
                'nome': p.get('name'),
                'foto': f"https://image.tmdb.org/t/p/w185{p['profile_path']}" if p.get('profile_path') else None
            }
            for p in creditos.get('crew', []) if p.get('job') == 'Director'
        ]

    result = (sinopse, poster_url, titulo_ptbr, streamings, trailer_key, elenco, diretores)
    _tmdb_cache[titulo_movielens] = result
    return result


# Grade dos 18 filmes mais populares — montada uma vez na inicialização
def _montar_card(titulo):
    _, poster, ptbr, *_ = buscar_info_tmdb(titulo)
    row     = filmes[filmes['title'] == titulo]
    generos = row.iloc[0]['genres'].split('|')[:2] if not row.empty else []
    return {'titulo': titulo, 'titulo_ptbr': ptbr, 'poster': poster, 'generos': generos}

print('Carregando grade de filmes populares...')
_top_titulos     = contagem_votos.sort_values(ascending=False).head(18).index.tolist()
with ThreadPoolExecutor(max_workers=18) as pool:
    _GRADE_POPULARES = list(pool.map(_montar_card, _top_titulos))
print('Pronto.')


def xai_detalhe(nome_filme, nota_usuario, user_id=None):
    """Texto de reforço XAI exibido na página de detalhes do filme."""
    generos = _generos_idx.get(nome_filme, set())
    gen_str = ', '.join(sorted(generos)) if generos else 'variados'
    texto   = f'Esse filme tem tudo a ver com {gen_str}. '

    if user_id:
        hist = buscar_historico_usuario(user_id)
        rel  = _historico_relevante(hist, nome_filme)
        if rel:
            nomes  = ' e '.join(h['titulo'] for h in rel)
            texto += f'Como você curtiu {nomes}, o VILU achou que esse estilo combina com você.'
        else:
            texto += 'Pelo perfil da comunidade aqui, é uma boa aposta pro seu gosto.'
    else:
        texto += 'A comunidade tá avaliando muito bem.'

    if nota_usuario:
        texto += f' Você já deu {nota_usuario} estrelas — isso ajuda o VILU a te conhecer melhor.'

    return texto


# ── rotas ─────────────────────────────────────────────────────────────────────

@app.route('/buscar_filmes')
@login_required
def buscar_filmes():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    return jsonify(
        filmes[filmes['title'].str.contains(q, case=False, na=False, regex=False)
        ]['title'].head(8).tolist()
    )


@app.route('/', methods=['GET', 'POST'])
@login_required
def home():
    recs             = []
    xai              = ''
    filme_escolhido  = ''
    poster_principal = None
    resumo           = ''
    streamings       = []
    trailer          = None
    modo = erro      = ''

    if request.method == 'POST':
        nome     = request.form.get('nome_filme', '').strip()
        uid      = session.get('user_id')
        unome    = session.get('user_nome', '')

        filme_escolhido, recs, xai, modo, erro = recomendar_hibrido(nome, uid, unome)

        if filme_escolhido:
            resumo, poster_principal, _, streamings, trailer, *_ = buscar_info_tmdb(filme_escolhido)

    def _com_poster(rec):
        _, poster, ptbr, *_ = buscar_info_tmdb(rec['titulo'])
        return {**rec, 'poster': poster, 'titulo_ptbr': ptbr}

    with ThreadPoolExecutor(max_workers=8) as pool:
        recs_enriquecidas = list(pool.map(_com_poster, recs))

    nota_atual    = None
    movie_id_atual = None
    if filme_escolhido:
        row_filme = filmes[filmes['title'] == filme_escolhido]
        if not row_filme.empty:
            movie_id_atual = int(row_filme.iloc[0]['movieId'])
            db  = get_db()
            row = db.execute(
                'SELECT nota FROM avaliacoes WHERE user_id = ? AND movie_id = ?',
                (session.get('user_id'), movie_id_atual)
            ).fetchone()
            db.close()
            if row:
                nota_atual = row['nota']

    return render_template('index.html',
        filme_escolhido       = filme_escolhido,
        lista_recomendacoes   = recs_enriquecidas,
        explicacao            = xai,
        resumo_principal      = resumo,
        streamings_principal  = streamings,
        trailer_key_principal = trailer,
        modo                  = modo,
        erro                  = erro,
        poster_principal      = poster_principal,
        movie_id_pesquisado   = movie_id_atual,
        nota_filme_pesquisado = nota_atual,
        filmes_destaque       = _GRADE_POPULARES,
        user_nome             = session.get('user_nome', '')
    )


@app.route('/principal')
@login_required
def principal():
    db   = get_db()
    rows = db.execute("""
        SELECT c.id, c.comentario, c.nota, c.titulo, c.movie_id, c.data,
               u.nome AS autor, u.id AS autor_id
        FROM comentarios c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.data DESC LIMIT 100
    """).fetchall()
    db.close()

    def _com_poster(p):
        _, poster, *_ = buscar_info_tmdb(p['titulo'])
        return {**dict(p), 'poster_url': poster}

    with ThreadPoolExecutor(max_workers=10) as pool:
        posts = list(pool.map(_com_poster, rows))

    return render_template('principal.html',
        posts     = posts,
        user_nome = session.get('user_nome', ''),
        user_id   = session['user_id']
    )


@app.route('/genero/<path:nome_genero>')
@login_required
def filmes_por_genero(nome_genero):
    mascara = filmes['genres'].str.contains(nome_genero, case=False, na=False)
    subset  = filmes[mascara].copy()

    if subset.empty:
        return render_template('404.html', mensagem=f'Nenhum filme em "{nome_genero}".'), 404

    subset['votos'] = subset['title'].map(contagem_votos).fillna(0)
    top = subset.sort_values('votos', ascending=False).head(20)['title'].tolist()

    def _card(titulo):
        _, poster, ptbr, *_ = buscar_info_tmdb(titulo)
        row     = filmes[filmes['title'] == titulo]
        generos = row.iloc[0]['genres'].split('|')[:2] if not row.empty else []
        return {'titulo': titulo, 'titulo_ptbr': ptbr, 'poster': poster, 'generos': generos}

    with ThreadPoolExecutor(max_workers=10) as pool:
        lista = list(pool.map(_card, top))

    return render_template('genero.html',
        genero       = nome_genero,
        filmes_lista = lista,
        user_nome    = session.get('user_nome', '')
    )


@app.route('/detalhes/<path:nome_filme>')
@login_required
def detalhes(nome_filme):
    busca = filmes[filmes['title'] == nome_filme]
    if busca.empty:
        return render_template('404.html', mensagem='Filme não encontrado.'), 404

    dados     = busca.iloc[0]
    movie_id  = int(dados['movieId'])
    generos   = dados['genres'].split('|')

    nota_media = '-'
    if nome_filme in dados_completos['title'].values:
        media      = dados_completos[dados_completos['title'] == nome_filme]['rating'].mean()
        nota_media = f'{media:.2f}'

    uid = session.get('user_id')
    db  = get_db()

    row_av       = db.execute(
        'SELECT nota FROM avaliacoes WHERE user_id = ? AND movie_id = ?', (uid, movie_id)
    ).fetchone()
    nota_usuario = row_av['nota'] if row_av else None

    comentarios = db.execute("""
        SELECT c.id, c.comentario, c.nota, c.data, u.nome AS autor, u.id AS autor_id
        FROM comentarios c
        JOIN users u ON c.user_id = u.id
        WHERE c.movie_id = ?
        ORDER BY c.data DESC
    """, (movie_id,)).fetchall()
    db.close()

    sinopse, poster_url, titulo_ptbr, streamings, trailer_key, elenco, diretores = buscar_info_tmdb(nome_filme)

    return render_template('detalhes.html',
        titulo       = nome_filme,
        titulo_ptbr  = titulo_ptbr,
        movie_id     = movie_id,
        generos      = generos,
        nota_media   = nota_media,
        sinopse      = sinopse,
        poster_url   = poster_url,
        streamings   = streamings,
        trailer_key  = trailer_key,
        elenco       = elenco,
        diretores    = diretores,
        nota_usuario = nota_usuario,
        comentarios  = comentarios,
        xai_detalhe  = xai_detalhe(nome_filme, nota_usuario, uid),
        user_nome    = session.get('user_nome', ''),
        user_id      = uid
    )


@app.route('/avaliar', methods=['POST'])
@login_required
def avaliar():
    movie_id = request.form.get('movie_id')
    titulo   = request.form.get('titulo')
    nota     = float(request.form.get('nota', 0))

    if not movie_id or not titulo or nota < 0.5:
        return redirect(url_for('home'))

    db = get_db()
    db.execute("""
        INSERT INTO avaliacoes (user_id, movie_id, titulo, nota)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, movie_id) DO UPDATE SET
            nota = excluded.nota, data = CURRENT_TIMESTAMP
    """, (session['user_id'], movie_id, titulo, nota))
    db.commit()
    db.close()

    atualizar_matriz()
    return redirect(url_for('detalhes', nome_filme=titulo))


@app.route('/comentar', methods=['POST'])
@login_required
def comentar():
    movie_id   = request.form.get('movie_id')
    titulo     = request.form.get('titulo')
    texto      = request.form.get('comentario', '').strip()
    uid        = session['user_id']

    if not texto or not 3 <= len(texto) <= 500:
        return redirect(url_for('detalhes', nome_filme=titulo))

    db  = get_db()
    row = db.execute(
        'SELECT nota FROM avaliacoes WHERE user_id = ? AND movie_id = ?', (uid, movie_id)
    ).fetchone()

    db.execute(
        'INSERT INTO comentarios (user_id, movie_id, titulo, nota, comentario) VALUES (?, ?, ?, ?, ?)',
        (uid, movie_id, titulo, row['nota'] if row else None, texto)
    )
    db.commit()
    db.close()
    return redirect(url_for('detalhes', nome_filme=titulo))


@app.route('/excluir_comentario/<int:cid>', methods=['POST'])
@login_required
def excluir_comentario(cid):
    db  = get_db()
    com = db.execute('SELECT titulo, user_id FROM comentarios WHERE id = ?', (cid,)).fetchone()

    titulo = ''
    if com and com['user_id'] == session['user_id']:
        db.execute('DELETE FROM comentarios WHERE id = ?', (cid,))
        db.commit()
        titulo = com['titulo']
    db.close()

    return redirect(url_for('detalhes', nome_filme=titulo) if titulo else url_for('principal'))


@app.route('/perfil')
@login_required
def perfil():
    uid = session['user_id']
    db  = get_db()

    avaliacoes  = db.execute(
        'SELECT titulo, movie_id, nota, data FROM avaliacoes WHERE user_id = ? ORDER BY data DESC',
        (uid,)
    ).fetchall()
    comentarios = db.execute(
        'SELECT id, titulo, nota, comentario, data FROM comentarios WHERE user_id = ? ORDER BY data DESC',
        (uid,)
    ).fetchall()
    db.close()

    return render_template('perfil.html',
        avaliacoes  = avaliacoes,
        comentarios = comentarios,
        user_nome   = session.get('user_nome', ''),
        user_id     = uid
    )


@app.route('/usuario/<int:uid>')
@login_required
def usuario_publico(uid):
    db      = get_db()
    usuario = db.execute('SELECT id, nome, criado_em FROM users WHERE id = ?', (uid,)).fetchone()

    if not usuario:
        return render_template('404.html', mensagem='Usuário não encontrado.'), 404

    comentarios = db.execute(
        'SELECT id, titulo, nota, comentario, data FROM comentarios WHERE user_id = ? ORDER BY data DESC',
        (uid,)
    ).fetchall()
    db.close()

    return render_template('usuario_publico.html',
        usuario     = usuario,
        comentarios = comentarios,
        user_nome   = session.get('user_nome', ''),
        user_id     = session['user_id']
    )


@app.errorhandler(404)
def not_found(e):
    return render_template('404.html', mensagem='Página não encontrada.'), 404


if __name__ == '__main__':
    app.run(debug=True)
