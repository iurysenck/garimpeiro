"""Persistência e deduplicação via SQLite.

Garante que uma vaga já vista não seja exibida de novo nas próximas rodadas.
"""
from __future__ import annotations

import datetime
import sqlite3

from sources import Job, empresa_generica, jaccard, sig_tokens

# Limiares da dedup fuzzy (título por Jaccard de tokens).
_SIM_MESMA_EMP = 0.60   # mesma empresa conhecida: títulos ~parecidos já bastam
_SIM_GENERICA = 0.80    # empresa genérica/omitida (agregador): exige título quase idêntico
_SIM_EMPRESA = 0.50     # quão parecidas as empresas precisam ser p/ contar como a mesma

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    uid        TEXT PRIMARY KEY,
    source     TEXT,
    title      TEXT,
    company    TEXT,
    url        TEXT,
    location   TEXT,
    remote     INTEGER,
    posted     TEXT,
    score      INTEGER,
    resumo     TEXT,
    motivo     TEXT,
    dica       TEXT,
    first_seen TEXT
);
"""

# Colunas adicionadas após a 1ª versão — migração idempotente.
_MIGRATIONS = (
    ("resumo", "TEXT"), ("motivo", "TEXT"), ("dica", "TEXT"),
    ("dkey", "TEXT"), ("freela", "INTEGER"), ("pitch", "TEXT"),
)


def _eh_dup(ct: frozenset, cc: frozenset, t: frozenset, c: frozenset) -> bool:
    """Duas vagas são a mesma? Compara tokens de título (Jaccard); se ambas têm
    empresa conhecida, exige empresa parecida; se uma é genérica (agregador),
    exige título quase idêntico para não juntar vagas diferentes por engano."""
    sim = jaccard(ct, t)
    if cc and c:  # ambas com empresa conhecida
        return sim >= _SIM_MESMA_EMP and jaccard(cc, c) >= _SIM_EMPRESA
    return sim >= _SIM_GENERICA


class Store:
    """Banco leve de vagas já processadas."""

    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.execute(_SCHEMA)
        for col, tipo in _MIGRATIONS:
            try:
                self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {tipo}")
            except sqlite3.OperationalError:
                pass  # coluna já existe
        self.conn.commit()

    def recent_sigs(self, days: int = 45) -> list[tuple[frozenset, frozenset]]:
        """Assinaturas (tokens de título, tokens de empresa) das vagas recentes,
        para a dedup fuzzy comparar candidatas contra o histórico."""
        limite = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT title, company FROM jobs WHERE first_seen >= ?", (limite,)
        ).fetchall()
        out: list[tuple[frozenset, frozenset]] = []
        for title, company in rows:
            csig = frozenset() if empresa_generica(company or "") else sig_tokens(company or "")
            out.append((sig_tokens(title or ""), csig))
        return out

    def filter_new(self, jobs: list[Job]) -> list[Job]:
        """Vagas inéditas. Três camadas de dedup:
        1) URL exata (uid)  2) tokens normalizados de título+empresa (dkey)
        3) fuzzy: título Jaccard vs. as já aceitas nesta rodada E o histórico recente.
        """
        seen_uid: set[str] = set()
        seen_dkey: set[str] = set()
        # histórico recente (tokens) p/ a camada fuzzy
        hist = self.recent_sigs(45)
        aceitas: list[tuple[frozenset, frozenset]] = []
        novas: list[Job] = []
        cur = self.conn.cursor()
        for job in jobs:
            uid, dkey = job.uid, job.dkey
            if uid in seen_uid or dkey in seen_dkey:
                continue
            row = cur.execute(
                "SELECT 1 FROM jobs WHERE uid = ? OR dkey = ?", (uid, dkey)
            ).fetchone()
            if row is not None:
                seen_uid.add(uid)
                seen_dkey.add(dkey)
                continue
            ct, cc = job.tsig, job.csig
            if ct and any(_eh_dup(ct, cc, t, c) for t, c in aceitas):
                continue  # quase-idêntica a outra desta rodada
            if ct and any(_eh_dup(ct, cc, t, c) for t, c in hist):
                continue  # quase-idêntica a uma já vista antes
            seen_uid.add(uid)
            seen_dkey.add(dkey)
            aceitas.append((ct, cc))
            novas.append(job)
        return novas

    def save(self, job: Job) -> None:
        """Marca a vaga como vista (com score, resumo e motivo)."""
        self.conn.execute(
            "INSERT OR IGNORE INTO jobs "
            "(uid, source, title, company, url, location, remote, posted, "
            " score, resumo, motivo, dica, dkey, freela, pitch, first_seen) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job.uid,
                job.source,
                job.title,
                job.company,
                job.url,
                job.location,
                int(job.remote),
                job.posted,
                job.score,
                job.resumo,
                job.motivo,
                job.dica,
                job.dkey,
                int(job.freela),
                job.pitch,
                datetime.datetime.now().isoformat(timespec="seconds"),
            ),
        )

    def recent_relevant(self, min_score: int, days: int) -> list[Job]:
        """Painel cumulativo: vagas relevantes vistas nos últimos `days` dias."""
        limite = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT source, title, company, url, location, remote, posted, "
            "       score, resumo, motivo, dica, freela, pitch "
            "FROM jobs WHERE score >= ? AND first_seen >= ? "
            "ORDER BY score DESC, first_seen DESC",
            (min_score, limite),
        ).fetchall()
        jobs: list[Job] = []
        for r in rows:
            jobs.append(
                Job(
                    source=r[0],
                    title=r[1],
                    company=r[2],
                    url=r[3],
                    location=r[4],
                    remote=bool(r[5]),
                    posted=r[6],
                    score=r[7],
                    resumo=r[8] or "",
                    motivo=r[9] or "",
                    dica=r[10] or "",
                    freela=bool(r[11]),
                    pitch=(r[12] if len(r) > 12 else "") or "",
                )
            )
        return jobs

    def save_all(self, jobs: list[Job]) -> None:
        for job in jobs:
            self.save(job)
        self.conn.commit()

    def purge_old(self, days: int = 60) -> int:
        """Limpa registros antigos para o banco não crescer pra sempre."""
        limite = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        cur = self.conn.execute("DELETE FROM jobs WHERE first_seen < ?", (limite,))
        self.conn.commit()
        return cur.rowcount

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
