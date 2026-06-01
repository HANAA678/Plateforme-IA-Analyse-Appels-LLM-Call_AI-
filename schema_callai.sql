-- ============================================================
--  CallAI  — Schéma PostgreSQL
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ============================================================
-- 1. TEAMS
-- ============================================================
CREATE TABLE teams (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(100) NOT NULL,
    supervisor_name VARCHAR(100),
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- 2. AGENTS
-- ============================================================
CREATE TABLE agents (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    team_id      UUID REFERENCES teams(id) ON DELETE SET NULL,
    full_name    VARCHAR(100) NOT NULL,
    initials     VARCHAR(3),
    email        VARCHAR(150) UNIQUE,
    avg_score    FLOAT   DEFAULT 0,
    total_calls  INTEGER DEFAULT 0,
    created_at   TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_agents_team ON agents(team_id);

-- ============================================================
-- 3. CRITERIA_CONFIG — grille d'évaluation (remplace settings)
--    Modifiable directement en SQL sans page dédiée
-- ============================================================
CREATE TABLE criteria_config (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    key         VARCHAR(50)  NOT NULL UNIQUE, -- "greeting", "listening"...
    label       VARCHAR(100) NOT NULL,         -- "Accueil & présentation"
    max_pts     INTEGER NOT NULL DEFAULT 20,
    description TEXT    NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    sort_order  INTEGER DEFAULT 0
);

-- Grille par défaut (total = 100 pts)
INSERT INTO criteria_config (key, label, max_pts, description, sort_order) VALUES
  ('greeting',   'Accueil & présentation',  20, 'Agent se présente, cite l''entreprise, formule d''accueil complète et professionnelle', 1),
  ('listening',  'Écoute active',           20, 'Reformulation du problème, empathie exprimée, aucune interruption du client', 2),
  ('resolution', 'Résolution du problème',  20, 'Problème clairement identifié, solution proposée ou escalade correctement effectuée', 3),
  ('script',     'Respect du script',       20, 'Toutes les étapes obligatoires du script de l''appel sont suivies dans l''ordre', 4),
  ('commercial', 'Proposition commerciale', 20, 'Offre de fidélité ou upsell proposé naturellement en fin d''appel', 5);

-- ============================================================
-- 4. CALLS — enregistrement brut de chaque appel
--    Nouveau : supervisor_notes, call_type, priority
-- ============================================================
CREATE TYPE call_status   AS ENUM ('pending','transcribed','evaluated','failed');
CREATE TYPE call_type_val AS ENUM ('reclamation','commercial','technique','information','autre');
CREATE TYPE call_priority AS ENUM ('normale','haute','urgente');

CREATE TABLE calls (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id            UUID REFERENCES agents(id) ON DELETE SET NULL,
    audio_url           TEXT NOT NULL,
    duration_seconds    INTEGER,
    called_at           TIMESTAMP NOT NULL,
    status              call_status   DEFAULT 'pending',
    call_type           call_type_val DEFAULT 'autre',
    priority            call_priority DEFAULT 'normale',

    -- Notes du superviseur saisies AVANT l'analyse (aide le LLM)
    supervisor_notes    TEXT,
    -- Points que le superviseur veut vérifier spécifiquement
    focus_points        TEXT,

    transcription_text  TEXT,
    language            VARCHAR(10) DEFAULT 'fr',
    waveform_data       JSONB,
    created_at          TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_calls_agent    ON calls(agent_id);
CREATE INDEX idx_calls_date     ON calls(called_at DESC);
CREATE INDEX idx_calls_status   ON calls(status);
CREATE INDEX idx_calls_type     ON calls(call_type);
CREATE INDEX idx_calls_priority ON calls(priority);
CREATE INDEX idx_calls_trgm     ON calls USING gin(transcription_text gin_trgm_ops);

-- ============================================================
-- 5. EVALUATIONS — résultat produit par Gemini LLM
-- ============================================================
CREATE TYPE compliance_status AS ENUM ('conforme','partiel','non-conforme');
CREATE TYPE sentiment_value   AS ENUM ('positif','neutre','negatif');
CREATE TYPE agent_sentiment   AS ENUM ('professionnel','neutre','non-professionnel');

CREATE TABLE evaluations (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    call_id          UUID UNIQUE REFERENCES calls(id) ON DELETE CASCADE,

    score_total      INTEGER CHECK (score_total BETWEEN 0 AND 100),

    -- Notes par critère : {"greeting":19, "listening":18, ...}
    -- Clés = criteria_config.key
    criteria         JSONB NOT NULL DEFAULT '{}',

    compliance       compliance_status,
    sentiment_client sentiment_value,
    sentiment_agent  agent_sentiment,

    -- Textes générés par Gemini
    summary          TEXT,        -- résumé 2 phrases
    strengths        TEXT,        -- points forts
    weaknesses       TEXT,        -- points faibles
    next_action      TEXT,        -- action CRM à faire

    -- Réponse aux focus_points du superviseur
    supervisor_feedback TEXT,     -- réponse aux points spécifiques demandés

    -- [{time_sec:0, time_label:"0:00", event:"Accueil conforme", type:"ok"}]
    timeline         JSONB DEFAULT '[]',

    -- ["remboursement","facturation","résiliation"]
    keywords         JSONB DEFAULT '[]',

    -- Justifications détaillées par critère
    -- {"greeting": "Agent s'est bien présenté mais a oublié le nom de l'entreprise"}
    criteria_justifications JSONB DEFAULT '{}',

    evaluated_at     TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_eval_call       ON evaluations(call_id);
CREATE INDEX idx_eval_score      ON evaluations(score_total);
CREATE INDEX idx_eval_compliance ON evaluations(compliance);
CREATE INDEX idx_eval_keywords   ON evaluations USING gin(keywords);

-- ============================================================
-- 6. AUDIO_METRICS — données extraites du signal WAV
-- ============================================================
CREATE TYPE noise_level_val AS ENUM ('low','medium','high');

CREATE TABLE audio_metrics (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    call_id             UUID UNIQUE REFERENCES calls(id) ON DELETE CASCADE,

    -- Répartition temps de parole
    agent_talk_pct      FLOAT,   -- % de parole agent
    client_talk_pct     FLOAT,   -- % de parole client
    silence_pct         FLOAT,   -- % de silence

    -- Silences
    silence_max_sec     INTEGER, -- durée du silence le plus long
    silences            JSONB DEFAULT '[]',
    -- [{start_sec:90, duration_sec:57, type:"hold"}]

    -- Diarisation : qui parle quand
    diarization         JSONB DEFAULT '[]',
    -- [{speaker:"agent", start_sec:0, end_sec:42, pct_width:8}]

    -- Rythme
    interruptions_count INTEGER DEFAULT 0,
    agent_wpm           INTEGER,  -- mots/min agent
    client_wpm          INTEGER,  -- mots/min client
    noise_level         noise_level_val DEFAULT 'low',

    -- Émotions vocales agent (scores 0.0-1.0, calculés par ML audio)
    -- {"professional":0.85, "empathetic":0.72, "stressed":0.18, "monotone":0.10}
    emotions_agent      JSONB DEFAULT '{}',

    -- Émotions vocales client
    -- {"frustrated":0.62, "satisfied":0.48, "angry":0.25, "neutral":0.30}
    emotions_client     JSONB DEFAULT '{}',

    computed_at         TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_audio_call    ON audio_metrics(call_id);
CREATE INDEX idx_audio_silence ON audio_metrics(silence_max_sec);

-- ============================================================
-- 7. ALERTS — alertes déclenchées automatiquement
-- ============================================================
CREATE TYPE alert_type_val AS ENUM (
    'churn_risk',      -- risque résiliation
    'compliance',      -- script non respecté
    'score_drop',      -- score trop bas
    'long_silence',    -- attente excessive
    'anger',           -- colère vocale client
    'focus_point'      -- point spécifique demandé par superviseur
);
CREATE TYPE alert_severity_val AS ENUM ('critical','medium','info');

CREATE TABLE alerts (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    call_id      UUID REFERENCES calls(id) ON DELETE CASCADE,
    agent_id     UUID REFERENCES agents(id) ON DELETE SET NULL,
    type         alert_type_val     NOT NULL,
    severity     alert_severity_val NOT NULL,
    message      TEXT NOT NULL,
    resolved     BOOLEAN DEFAULT FALSE,
    resolved_by  VARCHAR(100),          -- nom du superviseur qui a traité
    resolved_at  TIMESTAMP,
    triggered_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_alerts_call     ON alerts(call_id);
CREATE INDEX idx_alerts_agent    ON alerts(agent_id);
CREATE INDEX idx_alerts_resolved ON alerts(resolved);
CREATE INDEX idx_alerts_severity ON alerts(severity);
CREATE INDEX idx_alerts_type     ON alerts(type);

-- ============================================================
-- 8. COACHING_NOTES — fiche coaching par agent (1 par agent)
--    Accédée depuis la page Appels en cliquant sur un agent
-- ============================================================
CREATE TABLE coaching_notes (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id             UUID UNIQUE REFERENCES agents(id) ON DELETE CASCADE,
    -- UNIQUE : 1 seule fiche par agent (mise à jour à chaque regénération)

    -- Points faibles récurrents détectés sur les derniers appels
    weak_points          TEXT,
    -- Problèmes vocaux détectés (débit, ton, monotonie)
    vocal_issues         TEXT,
    -- Formation recommandée
    recommended_training TEXT,
    -- Appel exemple à écouter (le mieux noté de l'agent)
    example_call_id      UUID REFERENCES calls(id),

    -- Résumé des performances (30 derniers jours)
    performance_summary  TEXT,
    -- Score moyen calculé au moment de la génération
    avg_score_at_generation FLOAT,
    -- Nombre d'appels analysés pour générer cette fiche
    calls_analyzed       INTEGER DEFAULT 0,

    generated_at         TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_coaching_agent ON coaching_notes(agent_id);

-- ============================================================
-- VUES UTILES
-- ============================================================

-- Vue appels enrichis (JOIN principal pour liste + dashboard)
CREATE VIEW calls_enriched AS
SELECT
    c.id,
    c.called_at,
    c.duration_seconds,
    c.status,
    c.audio_url,
    c.waveform_data,
    c.language,
    c.call_type,
    c.priority,
    c.supervisor_notes,
    a.id           AS agent_id,
    a.full_name    AS agent_name,
    a.initials     AS agent_initials,
    t.id           AS team_id,
    t.name         AS team_name,
    e.score_total,
    e.compliance,
    e.sentiment_client,
    e.sentiment_agent,
    e.summary,
    e.next_action
FROM calls c
LEFT JOIN agents      a ON a.id = c.agent_id
LEFT JOIN teams       t ON t.id = a.team_id
LEFT JOIN evaluations e ON e.call_id = c.id;

-- Vue alertes actives enrichies (pour page Alertes)
CREATE VIEW alerts_active AS
SELECT
    al.id,
    al.type,
    al.severity,
    al.message,
    al.triggered_at,
    al.resolved,
    al.call_id,
    al.agent_id,
    a.full_name    AS agent_name,
    a.initials     AS agent_initials,
    c.called_at,
    c.duration_seconds,
    c.call_type,
    e.score_total,
    e.compliance
FROM alerts al
LEFT JOIN agents      a ON a.id = al.agent_id
LEFT JOIN calls       c ON c.id = al.call_id
LEFT JOIN evaluations e ON e.call_id = al.call_id
WHERE al.resolved = FALSE
ORDER BY
    CASE al.severity
        WHEN 'critical' THEN 1
        WHEN 'medium'   THEN 2
        ELSE 3
    END,
    al.triggered_at DESC;

-- ============================================================
-- FONCTIONS SQL
-- ============================================================

-- Recalcule avg_score et total_calls d'un agent (appelée après chaque évaluation)
CREATE OR REPLACE FUNCTION refresh_agent_stats(p_agent_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE agents
    SET
        avg_score   = COALESCE((
            SELECT ROUND(AVG(e.score_total)::numeric, 1)
            FROM calls c
            JOIN evaluations e ON e.call_id = c.id
            WHERE c.agent_id = p_agent_id
              AND c.called_at >= NOW() - INTERVAL '30 days'
        ), 0),
        total_calls = COALESCE((
            SELECT COUNT(*)
            FROM calls
            WHERE agent_id = p_agent_id
              AND called_at >= date_trunc('month', NOW())
        ), 0)
    WHERE id = p_agent_id;
END;
$$ LANGUAGE plpgsql;
--pour ajouter l alignement clientvs agent 
ALTER TABLE calls ADD COLUMN aligned_text TEXT;

