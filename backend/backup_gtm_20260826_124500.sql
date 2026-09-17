--
-- PostgreSQL database dump
--

\restrict 7idPnNyxemFpL6d7BEN0eAQbSJoX1h4G16pJpkzuDdbOp8AWzV99uT4xhHhx0dk

-- Dumped from database version 16.14 (Debian 16.14-1.pgdg12+1)
-- Dumped by pg_dump version 16.14 (Debian 16.14-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_executions; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.agent_executions (
    id uuid NOT NULL,
    workflow_run_id uuid NOT NULL,
    agent_id character varying(10) NOT NULL,
    agent_name character varying(100) NOT NULL,
    task_id character varying(100),
    status character varying(30) NOT NULL,
    input_payload jsonb,
    output_payload jsonb,
    error_message text,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.agent_executions OWNER TO gtm;

--
-- Name: agent_schedules; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.agent_schedules (
    agent_id character varying(10) NOT NULL,
    enabled boolean NOT NULL,
    cron character varying(100) NOT NULL,
    task_name character varying(200) NOT NULL,
    last_run_at timestamp without time zone,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.agent_schedules OWNER TO gtm;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO gtm;

--
-- Name: brand_assets; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.brand_assets (
    id uuid NOT NULL,
    title character varying(300) NOT NULL,
    content text NOT NULL,
    content_format character varying(50),
    icp_segment character varying(100),
    embedding public.vector(384),
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.brand_assets OWNER TO gtm;

--
-- Name: contacts; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.contacts (
    id uuid NOT NULL,
    email character varying(255) NOT NULL,
    first_name character varying(100),
    last_name character varying(100),
    title character varying(200),
    company character varying(200),
    company_domain character varying(200),
    linkedin_url character varying(500),
    company_size character varying(50),
    industry character varying(100),
    funding_stage character varying(50),
    tech_stack jsonb,
    geography character varying(100),
    annual_revenue character varying(50),
    employee_count integer,
    icp_score double precision,
    icp_score_breakdown jsonb,
    win_pattern_score double precision,
    signal_type character varying(50),
    signal_score double precision,
    latest_signal_at timestamp without time zone,
    readiness_score double precision NOT NULL,
    do_not_contact boolean NOT NULL,
    email_verified boolean NOT NULL,
    email_valid boolean,
    verified_at timestamp without time zone,
    enriched_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    source character varying(50),
    hubspot_id character varying(100),
    apollo_id character varying(100),
    user_input_id integer
);


ALTER TABLE public.contacts OWNER TO gtm;

--
-- Name: conversation_threads; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.conversation_threads (
    id uuid NOT NULL,
    contact_id uuid NOT NULL,
    outreach_log_id uuid,
    event_type character varying(50) NOT NULL,
    direction character varying(10) NOT NULL,
    channel character varying(20) NOT NULL,
    content text,
    subject character varying(500),
    intent character varying(50),
    intent_confidence double precision,
    readiness_score_delta double precision,
    readiness_score_after double precision,
    draft_generated boolean NOT NULL,
    draft_content text,
    slack_message_ts character varying(100),
    approved_by character varying(100),
    approved_at timestamp without time zone,
    sent_at timestamp without time zone,
    occurred_at timestamp without time zone NOT NULL,
    rejected_by character varying(100),
    rejected_at timestamp without time zone
);


ALTER TABLE public.conversation_threads OWNER TO gtm;

--
-- Name: deal_stage_history; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.deal_stage_history (
    id uuid NOT NULL,
    deal_id uuid NOT NULL,
    from_stage character varying(50),
    to_stage character varying(50) NOT NULL,
    days_in_from_stage integer,
    transitioned_at timestamp without time zone NOT NULL
);


ALTER TABLE public.deal_stage_history OWNER TO gtm;

--
-- Name: deals; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.deals (
    id uuid NOT NULL,
    hubspot_deal_id character varying(100),
    contact_id uuid,
    name character varying(300) NOT NULL,
    stage character varying(50) NOT NULL,
    amount double precision,
    close_date timestamp without time zone,
    owner_email character varying(200),
    days_in_current_stage integer NOT NULL,
    avg_response_time_hours double precision,
    stakeholder_count integer NOT NULL,
    meeting_count integer NOT NULL,
    risk_flags jsonb,
    risk_score double precision NOT NULL,
    budget_confirmed boolean,
    authority_confirmed boolean,
    need_confirmed boolean,
    timeline_confirmed boolean,
    outcome character varying(20),
    lost_reason character varying(300),
    stage_entered_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    deal_health_score double precision,
    win_probability double precision,
    buying_intent character varying(50),
    next_best_action text,
    stage_confidence double precision,
    objections jsonb
);


ALTER TABLE public.deals OWNER TO gtm;

--
-- Name: funnel_events; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.funnel_events (
    id uuid NOT NULL,
    event_type character varying(100) NOT NULL,
    contact_id uuid,
    deal_id uuid,
    agent_id character varying(10) NOT NULL,
    event_metadata jsonb,
    "timestamp" timestamp without time zone NOT NULL
);


ALTER TABLE public.funnel_events OWNER TO gtm;

--
-- Name: generated_content; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.generated_content (
    id uuid NOT NULL,
    title character varying(300) NOT NULL,
    content_format character varying(50) NOT NULL,
    icp_segment character varying(100),
    topic character varying(200),
    content text NOT NULL,
    brief jsonb,
    engagement_score double precision NOT NULL,
    used_in_outreach boolean NOT NULL,
    published boolean NOT NULL,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.generated_content OWNER TO gtm;

--
-- Name: outreach_drafts; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.outreach_drafts (
    id uuid NOT NULL,
    contact_id uuid NOT NULL,
    signal_id uuid,
    subject character varying(500) NOT NULL,
    body text NOT NULL,
    business_case character varying(100) NOT NULL,
    matched_services jsonb NOT NULL,
    channel character varying(50) NOT NULL,
    status character varying(50) NOT NULL,
    approval_state character varying(50) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.outreach_drafts OWNER TO gtm;

--
-- Name: outreach_log; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.outreach_log (
    id uuid NOT NULL,
    contact_id uuid NOT NULL,
    campaign_id character varying(100),
    campaign_type character varying(50) NOT NULL,
    channel character varying(20) NOT NULL,
    subject character varying(500),
    body_preview text,
    prompt_variant_id character varying(50),
    signal_id uuid,
    outreach_provider_message_id character varying(100),
    opened boolean NOT NULL,
    open_count integer NOT NULL,
    replied boolean NOT NULL,
    meeting_booked boolean NOT NULL,
    unsubscribed boolean NOT NULL,
    bounced boolean NOT NULL,
    sent_at timestamp without time zone NOT NULL,
    replied_at timestamp without time zone,
    sequence_step integer DEFAULT 0 NOT NULL,
    call_script text,
    linkedin_note text
);


ALTER TABLE public.outreach_log OWNER TO gtm;

--
-- Name: pending_actions; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.pending_actions (
    id uuid NOT NULL,
    action_type character varying(50) NOT NULL,
    entity_type character varying(50) NOT NULL,
    entity_id character varying(100) NOT NULL,
    recommended_value character varying(500),
    current_value character varying(500),
    reason text,
    agent_id character varying(10) NOT NULL,
    status character varying(20) NOT NULL,
    slack_message_ts character varying(100),
    approved_by character varying(100),
    created_at timestamp without time zone NOT NULL,
    approved_at timestamp without time zone,
    expires_at timestamp without time zone
);


ALTER TABLE public.pending_actions OWNER TO gtm;

--
-- Name: prompt_variants; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.prompt_variants (
    id character varying(50) NOT NULL,
    signal_type character varying(50) NOT NULL,
    channel character varying(20) NOT NULL,
    system_prompt text NOT NULL,
    user_prompt_template text NOT NULL,
    reply_rate double precision NOT NULL,
    send_count integer NOT NULL,
    reply_count integer NOT NULL,
    meeting_count integer NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.prompt_variants OWNER TO gtm;

--
-- Name: revenue_forecasts; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.revenue_forecasts (
    id uuid NOT NULL,
    forecast_30d double precision,
    forecast_60d double precision,
    forecast_90d double precision,
    current_pipeline_value double precision,
    bottleneck_stage character varying(50),
    bottleneck_description text,
    recommended_lever text,
    stage_conversion_rates jsonb,
    stage_velocity_days jsonb,
    calculated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.revenue_forecasts OWNER TO gtm;

--
-- Name: signal_conversion_registry; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.signal_conversion_registry (
    id uuid NOT NULL,
    signal_type character varying(50) NOT NULL,
    conversion_rate double precision NOT NULL,
    sample_size integer NOT NULL,
    last_calibrated_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.signal_conversion_registry OWNER TO gtm;

--
-- Name: signal_events; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.signal_events (
    id uuid NOT NULL,
    contact_id uuid NOT NULL,
    signal_type character varying(50) NOT NULL,
    signal_source character varying(100) NOT NULL,
    confidence double precision NOT NULL,
    conversion_weight double precision,
    raw_data jsonb,
    processed boolean NOT NULL,
    triggered_outreach boolean NOT NULL,
    detected_at timestamp without time zone NOT NULL,
    sequence_step integer DEFAULT 0 NOT NULL,
    next_step_due_at timestamp without time zone
);


ALTER TABLE public.signal_events OWNER TO gtm;

--
-- Name: user_inputs; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.user_inputs (
    id integer NOT NULL,
    our_company_name character varying(300) DEFAULT ''::character varying NOT NULL,
    our_services character varying(300) NOT NULL,
    target_location character varying(200) NOT NULL,
    target_industries character varying(300),
    target_company_size character varying(50) NOT NULL,
    target_keywords text,
    target_job_titles character varying(200) NOT NULL
);


ALTER TABLE public.user_inputs OWNER TO gtm;

--
-- Name: user_inputs_id_seq; Type: SEQUENCE; Schema: public; Owner: gtm
--

CREATE SEQUENCE public.user_inputs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_inputs_id_seq OWNER TO gtm;

--
-- Name: user_inputs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: gtm
--

ALTER SEQUENCE public.user_inputs_id_seq OWNED BY public.user_inputs.id;


--
-- Name: workflow_runs; Type: TABLE; Schema: public; Owner: gtm
--

CREATE TABLE public.workflow_runs (
    id uuid NOT NULL,
    workflow_name character varying(100) NOT NULL,
    status character varying(30) NOT NULL,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    input_payload jsonb,
    output_payload jsonb,
    error_message text,
    current_agent character varying(10),
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.workflow_runs OWNER TO gtm;

--
-- Name: user_inputs id; Type: DEFAULT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.user_inputs ALTER COLUMN id SET DEFAULT nextval('public.user_inputs_id_seq'::regclass);


--
-- Data for Name: agent_executions; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.agent_executions (id, workflow_run_id, agent_id, agent_name, task_id, status, input_payload, output_payload, error_message, started_at, completed_at, created_at) FROM stdin;
0e0e9b70-e803-4195-9725-cb9d6f80dbfb	e49ec4cd-09f2-47f5-b80d-3d0c782f76b0	A1	Prospect Intelligence	0dd06a05-da15-44e0-a41b-daa8381f402b	completed	{}	{"agent": "A1", "reason": "apollo_people_search_empty", "contacts": [], "provider": "apollo", "_agent_id": "A1", "raw_count": 0, "contact_ids": [], "saved_count": 0, "scored_count": 0, "provider_page": 1, "updated_count": 0, "qualified_count": 0, "_workflow_run_id": "e49ec4cd-09f2-47f5-b80d-3d0c782f76b0", "discovery_method": "people_search_bulk_match", "inserted_contact_ids": []}	\N	2026-08-25 12:10:33.614394	2026-08-25 12:10:56.114739	2026-08-25 12:10:26.088952
40b90d13-3e9f-46fa-864d-162ae4e7e2d8	75ea627e-20d1-4a7f-acf2-b20aeea2e36f	A1	Prospect Intelligence	1b1a0a0d-0efe-4f5e-b942-ceae7e4ef10e	queued	{}	\N	\N	\N	\N	2026-08-25 12:21:44.765895
c2247ae8-101d-4ab7-8220-a8b1b21bca70	6a4fc190-b436-46f4-8897-0e7f4f9ddab6	A1	Prospect Intelligence	a11a884e-95c0-4b74-a9c3-e7ee5a5a1ea1	completed	{}	{"agent": "A1", "reason": "apollo_contacts_persisted", "contacts": ["froy@balsambrands.com", "nichole.sprutte@skbcases.com", "jkbrandt@jacksonkelly.com", "bill.wallace@interceptpharma.com", "vdakshin@meso-scale.com"], "provider": "apollo", "_agent_id": "A1", "raw_count": 18, "contact_ids": ["e1a49d9d-71c7-4f4c-a39e-ecaf53abdfd5", "5d7d64f3-82ab-4226-9a86-50735600558c", "ac3fa0a5-f9cc-47da-9254-2671f62b730b", "374dde64-737e-44e1-adfa-e8543dd612e5", "9e92a2dc-b991-4a37-aa5c-dea61a203acd", "6c1959dd-efed-43fa-b57d-3b934c626568", "c395980f-6808-4076-916b-6b9bad90f22d", "6130fba6-f73a-4eba-b518-90f4e92cded5", "11e15b36-16c1-47aa-ac39-b801d53188a2", "855a05b3-2411-4944-94b4-07b7a267dab0", "db1ce271-0143-4427-8cd4-4526fd9ff07b", "501fe7c5-adae-4aa7-8db2-68b4b510dc07", "988ca8df-0a66-4fba-b983-6e0eeac2fc4d", "c6cf1cbf-f9ef-4514-a7e5-889da759b3f8", "89c38ffc-1c5b-4a3e-ab29-aa5acc42c7f3", "64a580f7-d592-439b-80bf-150d4f6820f7", "d04c09bc-0011-4c51-8ea2-1c9ffa9b4aa3", "2587ef84-0f89-4a36-8b60-d55596fd0415"], "saved_count": 18, "scored_count": 18, "provider_page": 10, "updated_count": 0, "qualified_count": 18, "_workflow_run_id": "6a4fc190-b436-46f4-8897-0e7f4f9ddab6", "discovery_method": "people_search_bulk_match", "inserted_contact_ids": ["e1a49d9d-71c7-4f4c-a39e-ecaf53abdfd5", "5d7d64f3-82ab-4226-9a86-50735600558c", "ac3fa0a5-f9cc-47da-9254-2671f62b730b", "374dde64-737e-44e1-adfa-e8543dd612e5", "9e92a2dc-b991-4a37-aa5c-dea61a203acd", "6c1959dd-efed-43fa-b57d-3b934c626568", "c395980f-6808-4076-916b-6b9bad90f22d", "6130fba6-f73a-4eba-b518-90f4e92cded5", "11e15b36-16c1-47aa-ac39-b801d53188a2", "855a05b3-2411-4944-94b4-07b7a267dab0", "db1ce271-0143-4427-8cd4-4526fd9ff07b", "501fe7c5-adae-4aa7-8db2-68b4b510dc07", "988ca8df-0a66-4fba-b983-6e0eeac2fc4d", "c6cf1cbf-f9ef-4514-a7e5-889da759b3f8", "89c38ffc-1c5b-4a3e-ab29-aa5acc42c7f3", "64a580f7-d592-439b-80bf-150d4f6820f7", "d04c09bc-0011-4c51-8ea2-1c9ffa9b4aa3", "2587ef84-0f89-4a36-8b60-d55596fd0415"]}	\N	2026-08-25 16:54:01.897282	2026-08-25 16:54:15.047549	2026-08-25 16:53:59.236691
\.


--
-- Data for Name: agent_schedules; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.agent_schedules (agent_id, enabled, cron, task_name, last_run_at, updated_at) FROM stdin;
A2	t	0 * * * *	app.workers.scheduler_tasks.run_signal_agent	2026-08-26 07:00:00.012171	2026-08-26 07:00:00.218366
A1	t	0 8 * * 1	app.workers.scheduler_tasks.run_prospect_agent	2026-08-24 08:00:00.010208	2026-08-24 08:00:00.333142
A6	t	0 9 * * 2	app.workers.scheduler_tasks.run_content_agent	2026-08-25 09:00:00.007967	2026-08-25 09:00:00.641287
\.


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.alembic_version (version_num) FROM stdin;
cdd7e925ba8b
\.


--
-- Data for Name: brand_assets; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.brand_assets (id, title, content, content_format, icp_segment, embedding, created_at) FROM stdin;
86c6c6f3-20e6-4436-b258-7bf4da38a686	CSL Case Study	Cloud Science Labs scaled their sales development team by 40% using our go-to-market automation solutions.	case_study	SaaS	[0.024956988,-0.0031090814,-0.010635256,-0.019989073,0.017875375,-0.026039885,-0.07509855,0.06516359,-0.010146865,0.04619954,0.008722744,0.006646894,0.041116316,0.02356924,0.041341953,-0.024926018,-0.027854716,-0.10326393,-0.0476532,-0.09599812,-0.10126551,-0.054911237,-0.023853967,-0.013483555,0.04565932,0.037947666,-0.05295022,-0.022952123,-0.05111542,-0.026852276,-0.09573307,0.0071672765,0.06977035,0.080325104,-0.018838963,-0.03420707,-0.015445305,0.0071226903,0.036810428,0.02195813,-0.004745162,-0.09765459,-0.089225374,0.023143237,0.010920689,-0.022866504,-0.021072779,-0.024284113,0.006464595,0.05236164,-0.048151363,-0.038559943,-0.024381341,-0.041670464,-0.016722739,0.033698346,0.055642325,0.0069240276,0.061915144,-0.029873928,0.021911325,-0.10115593,-0.038312647,0.07072314,0.024542155,0.059791837,-0.035410706,0.0016619434,-0.04701584,-0.07347706,0.01709563,-0.061850823,0.025682488,0.04227057,0.04972246,0.0484908,-0.0052538333,-0.016139818,0.108104356,0.020220803,0.026543107,-0.07656342,-0.093624145,0.1496065,-0.13411824,0.042872243,0.06863467,0.03895309,0.07313336,0.010587868,0.035895262,-0.036365308,-0.04638843,0.004359927,-0.07743822,0.0044428147,-0.061792146,-0.0779101,0.046073057,-0.038284797,-0.03200871,0.014552879,0.12759286,-0.07755274,-0.053946856,-0.01502899,-0.01104153,0.07766598,0.08635096,-0.0077741006,-0.022547645,-0.03167514,-0.051629584,0.0030938399,0.045039095,-0.014886274,0.0018566415,0.020713786,-0.031304132,-0.022063361,0.07516269,0.05571926,-0.009301735,-0.043266863,-0.013106496,0.046637803,-0.13089822,-2.9416076e-33,-0.035744816,0.013912547,0.045497242,-0.019019848,0.055211026,-0.012941085,0.030077618,0.07776814,-0.13058491,-0.028236164,-0.064321786,0.11920886,-0.0009011692,0.017402118,0.028497558,0.011016216,-0.028174426,0.077392094,-0.009040758,0.0008832114,-0.020918466,-0.033266727,0.028105518,0.059865516,0.059565067,-0.04088957,-0.031813543,0.041254163,0.109073766,0.0042284066,-0.03626658,-0.023515152,-0.015832623,0.020380657,-0.024463834,0.002932069,-0.05744129,-0.04470798,0.04812694,0.09754137,-0.065829135,0.046389945,-0.003929382,0.012202637,-0.034104407,0.026011951,0.013988207,-0.021001376,0.112968884,0.053458128,-0.039430667,-0.0026108222,0.073818475,0.026883515,0.054483112,0.016721778,0.030563133,-0.04537194,-0.0030759715,0.0015362962,-0.03759394,0.026460283,-0.047684852,0.0008031606,-0.015334135,-0.018745245,-0.0041346564,0.021123558,0.06929999,0.03706854,0.047071833,0.007306387,-0.021309882,-0.020110901,0.0026964704,-0.0591758,0.005796315,0.06867821,0.05308643,-0.031816192,-0.06849475,-0.0052518947,-0.015147727,-0.015435391,-0.013423364,0.047026716,0.03131097,0.039957345,-0.09467589,-0.01401613,-0.008202818,-0.041613203,-0.0026608722,0.064175345,-0.04535104,1.1957046e-33,-0.09913175,-0.07355891,-0.08223313,0.1365027,0.031288076,0.0077966372,0.030949343,-0.011554689,0.040343743,0.10793735,0.0012173796,0.03293745,-0.014853237,-0.017930191,0.006124101,0.005438278,-0.0075807525,-0.071628526,0.013029384,-0.010305268,0.009697957,0.045957875,0.015872106,0.05477773,0.04981624,-0.032507766,-0.0599501,-0.010213323,0.025756568,-0.028593957,-0.0008815866,-0.027830219,0.003625682,0.025349014,0.035072524,-0.011852051,-0.017845359,0.0019756507,0.09564928,-0.02662223,-0.026849572,-0.057038166,-0.06767166,-0.030708559,0.019743267,0.08358244,0.0776049,0.02921392,-0.024357863,-0.042578932,-0.0033551955,0.0664975,-0.0064766333,-0.051178582,-0.068726204,0.039569855,0.042836964,0.045274023,-0.13290626,0.026586402,0.034484327,-0.03366489,0.08903178,-0.007101771,-0.06494347,0.046676207,0.05054335,0.103526935,-0.10658674,-0.056510523,-0.009406231,-0.04463461,0.02091932,-0.039912328,-0.13799056,-0.07243986,-0.033466093,-0.08425438,0.03204261,0.0136222765,-0.02882335,0.06599489,0.07142451,0.04447416,-0.051362112,0.0077368566,0.054205343,0.014820162,-0.0059303883,0.08165143,-0.10545009,-0.025823753,-0.0011662313,0.04225837,-0.04164523,-2.093567e-08,0.0454489,0.06481202,0.07763996,0.09256426,0.026626179,0.052012853,0.026535695,0.11763016,0.0505107,0.07428395,-0.020820402,-0.11417598,-0.069856584,0.13009627,0.036335368,-0.011201688,0.015302938,0.06772724,-0.02118518,-0.07449585,-0.004917442,0.0675979,0.021485766,0.0061004935,0.0057979426,0.026278278,-0.011075459,0.034638148,-0.07122733,-0.0863651,-0.052040506,-0.04547464,-0.04898528,0.029311307,0.10788384,-0.06881501,-0.016089767,0.009252326,0.03191864,0.0335857,-0.045468383,0.02191567,-0.035537265,0.03422416,-0.04002547,-0.0102988565,-0.048761558,-0.01388363,0.03306157,0.0040410487,0.05649277,0.036154184,-0.06372432,0.056223843,0.025638739,0.022935746,0.009264261,-0.06547978,-0.023043115,0.05998265,-0.0092691565,-0.015391868,0.019992633,0.0015219606]	2026-08-17 06:08:10.239068
\.


--
-- Data for Name: contacts; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.contacts (id, email, first_name, last_name, title, company, company_domain, linkedin_url, company_size, industry, funding_stage, tech_stack, geography, annual_revenue, employee_count, icp_score, icp_score_breakdown, win_pattern_score, signal_type, signal_score, latest_signal_at, readiness_score, do_not_contact, email_verified, email_valid, verified_at, enriched_at, created_at, updated_at, source, hubspot_id, apollo_id, user_input_id) FROM stdin;
796ed0ed-f1a1-467e-b9d1-18cd032b91c1	pfr@eclear.com	Patrick	Frenzel	Chief Technology Officer (CTO)	eClear | borderfree	eclear.com	http://www.linkedin.com/in/patrick-frenzel-225642178	69	information technology & services		[]	Bonn	\N	\N	78	{"title": 25, "method": "rule_based", "industry": 16, "seniority": 10, "company_size": 22, "funding_stage": 5, "has_tech_stack": 0}	78	news_expansion	22	2026-08-26 04:56:44.804569	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.709892	2026-08-26 04:56:44.879125	apollo	\N	\N	2
b7d138b9-3dd0-40ea-b1c1-7788aafdefd0	pacificmuhindo@bgsgroup.co.zm	Pacific	Muhindo	Chief Technology Officer - CTO	Bridging Gap Solutions	bgsgroup.co.zm	http://www.linkedin.com/in/pacific-muhindo	130	information technology & services		[]	Zambia	\N	\N	78	{"title": 25, "method": "rule_based", "industry": 16, "seniority": 10, "company_size": 22, "funding_stage": 5, "has_tech_stack": 0}	78	news_expansion	22	2026-08-26 07:01:30.37466	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.640406	2026-08-26 07:01:30.387694	apollo	\N	\N	2
cbeb6112-d896-428b-8aa2-c8e7da2974b7	ibrahim.debbagh@yodlee.com	Ibrahim	Debbagh	Chief Technology Officer (CTO)	Yodlee		http://www.linkedin.com/in/debbagh	350	financial services		[]	Los Angeles	\N	\N	70	{"title": 25, "method": "rule_based", "industry": 5, "seniority": 10, "company_size": 25, "funding_stage": 5, "has_tech_stack": 0}	70	news_expansion	22	2026-08-26 07:01:30.376231	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.713885	2026-08-26 07:01:30.387697	apollo	\N	\N	2
010de45d-4272-462c-9f04-baf0115ad2ac	chris.davis@salenova.com	Chris	Davis	Head of Growth	SaleNova	salenova.com	\N	11-50	SaaS	Seed	[]	Atlanta, GA	\N	\N	65	{"title": 18, "method": "rule_based", "industry": 20, "company_size": 18, "funding_stage": 20, "has_tech_stack": 5}	65	\N	\N	\N	57.67591787655885	f	t	t	2026-08-01 17:29:15.411377	2026-08-18 17:29:15.411385	2026-08-25 17:29:15.422573	2026-08-25 17:52:33.646773	apollo	\N	\N	12
25ad487a-284d-49ce-aae0-a9edb5261b91	rachel.green@outbound.ai	Rachel	Green	Director of Sales	Outbound AI	outbound.ai	\N	11-50	AI SaaS	Series A	[]	Miami, FL	\N	\N	68	{"title": 18, "method": "rule_based", "industry": 20, "company_size": 18, "funding_stage": 20, "has_tech_stack": 5}	68	funding_round	60	2026-08-24 03:29:15.528607	59.86455745538807	f	t	t	2026-07-28 17:29:15.411268	2026-08-21 17:29:15.411285	2026-08-25 17:29:15.422558	2026-08-25 17:52:33.646773	apollo	\N	\N	12
2e81530f-14eb-4e6b-8c2f-14cee780d3e7	priya.patel@revstack.ai	Priya	Patel	Director of Revenue Ops	RevStack AI	revstack.ai	\N	11-50	AI/ML SaaS	Series A	[]	Austin, TX	\N	\N	85	{"title": 18, "method": "rule_based", "industry": 20, "company_size": 18, "funding_stage": 20, "has_tech_stack": 5}	85	job_posting	45	2026-08-23 17:29:15.528124	59.509341525125095	f	t	t	2026-07-26 17:29:15.410282	2026-08-13 17:29:15.410297	2026-08-25 17:29:15.422478	2026-08-25 17:52:33.646773	apollo	\N	\N	12
45eb8c14-b33e-4710-8e6f-c0659dbecc25	james.miller@salesforge.com	James	Miller	Sales Director	SalesForge	salesforge.com	\N	201-500	Sales Technology	Series B	[]	Denver, CO	\N	\N	76	{"title": 18, "method": "rule_based", "industry": 20, "company_size": 18, "funding_stage": 20, "has_tech_stack": 5}	76	job_posting,news_expansion	43	2026-08-26 05:01:36.953789	33.11383513978895	f	t	t	2026-08-15 17:29:15.410857	2026-08-15 17:29:15.410873	2026-08-25 17:29:15.422518	2026-08-26 05:01:37.623105	apollo	\N	\N	12
b9befa8b-a1cc-4e22-af29-c90f0724f0c4	anna.thompson@growthleap.io	Anna	Thompson	CRO	GrowthLeap	growthleap.io	\N	11-50	E-commerce	Seed	[]	Los Angeles, CA	\N	\N	72	{"title": 18, "method": "rule_based", "industry": 20, "company_size": 18, "funding_stage": 20, "has_tech_stack": 5}	72	news_expansion	25	2026-08-24 19:29:15.528475	21.839004252238624	f	t	t	2026-08-19 17:29:15.411034	2026-08-22 17:29:15.411055	2026-08-25 17:29:15.422531	2026-08-25 17:52:33.646773	apollo	\N	\N	12
01636f82-ee99-4e99-9bba-e92a3af40853	david.kim@metrics360.com	David	Kim	VP Sales Operations	Metrics360	metrics360.com	\N	51-200	Analytics SaaS	Series A	[]	Seattle, WA	\N	\N	70	{"title": 18, "method": "rule_based", "industry": 20, "company_size": 18, "funding_stage": 20, "has_tech_stack": 5}	70	news_expansion	22	2026-08-26 07:01:30.377548	72.1114906018277	f	t	t	2026-08-24 17:29:15.411162	2026-08-17 17:29:15.41117	2026-08-25 17:29:15.422545	2026-08-26 07:01:30.387677	apollo	\N	\N	12
5400a977-f9f0-43c4-9ca2-46317d7b8a25	sarah.chen@growthops.io	Sarah	Chen	VP of Sales	GrowthOps	growthops.io	\N	51-200	SaaS	Series B	[]	San Francisco, CA	\N	\N	91	{"title": 18, "method": "rule_based", "industry": 20, "company_size": 18, "funding_stage": 20, "has_tech_stack": 5}	91	news_expansion	22	2026-08-26 07:01:30.378758	45	f	t	t	2026-08-04 17:29:15.409657	2026-08-19 17:29:15.409717	2026-08-25 17:29:15.422431	2026-08-26 07:01:30.387687	apollo	\N	\N	12
caf9089c-85e9-4cba-8f79-c53ae6b26ced	lisa.wang@pipelineco.io	Lisa	Wang	VP Revenue	PipelineCo	pipelineco.io	\N	51-200	SaaS	Series A	[]	Boston, MA	\N	\N	79	{"title": 18, "method": "rule_based", "industry": 20, "company_size": 18, "funding_stage": 20, "has_tech_stack": 5}	79	funding_round	60	2026-08-25 01:29:15.52829	22.383058262203235	f	t	t	2026-08-01 17:29:15.410533	2026-08-16 17:29:15.410541	2026-08-25 17:29:15.422505	2026-08-25 17:52:33.646773	apollo	\N	\N	12
1e79c123-e779-408a-bcf6-49936e2a62a6	marcus.johnson@scalepath.com	Marcus	Johnson	Chief Revenue Officer	ScalePath	scalepath.com	\N	201-500	B2B Technology	Series C	[]	New York, NY	\N	\N	88	{"title": 18, "method": "rule_based", "industry": 20, "company_size": 18, "funding_stage": 20, "has_tech_stack": 5}	88	new_hire	65	2026-08-24 18:29:15.528016	25	f	t	t	2026-07-31 17:29:15.41012	2026-08-11 17:29:15.410147	2026-08-25 17:29:15.422462	2026-08-25 17:52:33.646773	apollo	\N	\N	12
08f266c6-0bb0-4adb-b7f4-555d52ecf565	shreelakshmipp2003@gmail.com	Lauren	Bell	VP of Sales Operations	Galvin Technologies	galvintech.com	https://www.linkedin.com/in/lauren-bell-galvin	51-200	IT Services & Salesforce Consulting	Series B	[]	Indianapolis, IN	\N	120	95	{"title": 25, "industry": 20, "company_size": 25, "funding_stage": 20, "has_tech_stack": 5}	95	\N	\N	\N	35	f	t	t	2026-08-20 17:29:16.748548	2026-08-20 17:29:16.748644	2026-08-25 17:29:16.752718	2026-08-25 17:52:33.518059	apollo	\N	\N	9
fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	tom.wright@databridge.co	Tom	Wright	Head of Sales	DataBridge	databridge.co	\N	51-200	Data Infra	Series B	[]	Chicago, IL	\N	\N	83	{"title": 18, "method": "rule_based", "industry": 20, "company_size": 18, "funding_stage": 20, "has_tech_stack": 5}	83	news_expansion	22	2026-08-26 07:01:30.379903	25	f	t	t	2026-07-30 17:29:15.410429	2026-08-20 17:29:15.410438	2026-08-25 17:29:15.422491	2026-08-26 07:01:30.3877	apollo	\N	\N	12
5c44dac1-1446-45f4-8af1-023b34905328	laurent.pujol@aosis.net	Laurent	Pujol	Chief Technology Officer (CTO)	AOSIS	aosis.net	http://www.linkedin.com/in/laurentpujol	80	information technology & services		[]	Toulouse	\N	\N	78	{"title": 25, "method": "rule_based", "industry": 16, "seniority": 10, "company_size": 22, "funding_stage": 5, "has_tech_stack": 0}	78	news_expansion	22	2026-08-26 07:01:30.381094	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.706025	2026-08-26 07:01:30.387691	apollo	\N	\N	2
356f9fdb-ade0-45ea-901b-cd02ed3e389e	eduardo.chinellato@olos.com.br	Eduardo	Chinellato	Chief Technology Officer (CTO)	Olos Tecnologia	olos.com.br	http://www.linkedin.com/in/eduardo-chinellato-53013924	240	information technology & services		[]	Sao Paulo	\N	\N	81	{"title": 25, "method": "rule_based", "industry": 16, "seniority": 10, "company_size": 25, "funding_stage": 5, "has_tech_stack": 0}	81	\N	\N	\N	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.633225	2026-08-25 17:29:16.633236	apollo	\N	\N	2
68dfa008-4802-4da9-ac90-e6bd447e058e	medappa@kavintech.com	Madhu	Medappa	Chief Technology Officer (CTO)	Kavintech Corporation	kavintech.com	http://www.linkedin.com/in/madhu-medappa-670b4716b	71	information technology & services		[]	Bengaluru	\N	\N	78	{"title": 25, "method": "rule_based", "industry": 16, "seniority": 10, "company_size": 22, "funding_stage": 5, "has_tech_stack": 0}	78	\N	\N	\N	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.649439	2026-08-25 17:29:16.649447	apollo	\N	\N	2
598c49a1-8aea-4b8f-89a0-c3eb034a298f	mceitlin@intuit.ar	Marcelo	Ceitlin	Chief Technology Officer (CTO)	Intuit Salud	intuitsalud.ar	http://www.linkedin.com/in/marcelo-ceitlin-9487571	63	information technology & services		[]	Buenos Aires	\N	\N	78	{"title": 25, "method": "rule_based", "industry": 16, "seniority": 10, "company_size": 22, "funding_stage": 5, "has_tech_stack": 0}	78	\N	\N	\N	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.653438	2026-08-25 17:29:16.653444	apollo	\N	\N	2
495f7037-42f0-406c-ba46-c50468d73553	durai.raj@lmteq.com	Durai	Raj	Chief Technology Officer (CTO)	LMTEQ	lmteq.com	http://www.linkedin.com/in/durai-raj-b716134	57	information technology & services		[]	Chennai	\N	\N	78	{"title": 25, "method": "rule_based", "industry": 16, "seniority": 10, "company_size": 22, "funding_stage": 5, "has_tech_stack": 0}	78	\N	\N	\N	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.657174	2026-08-25 17:29:16.657181	apollo	\N	\N	2
1f2aec2e-5535-41e9-8ea3-19b7312529bf	rich@protect247.com	Richard	Neary	Chief Technology Officer (CTO)	Life Protect 24/7	lifeprotect247.com	http://www.linkedin.com/in/richard-neary-6a289a2a	510	hospital & health care		[]	Virginia Beach	\N	\N	72	{"title": 25, "method": "rule_based", "industry": 14, "seniority": 10, "company_size": 18, "funding_stage": 5, "has_tech_stack": 0}	72	\N	\N	\N	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.681244	2026-08-25 17:29:16.681253	apollo	\N	\N	2
bf13172d-82e6-42e9-8a86-16a356bae5ca	cmaturana@inticousa.com	Carlos	Maturana	Chief Technology Officer (CTO)	IntiCo AI	intico.ai	http://www.linkedin.com/in/carlos-maturana-37469b55	100	information technology & services		[]	Chile	\N	\N	78	{"title": 25, "method": "rule_based", "industry": 16, "seniority": 10, "company_size": 22, "funding_stage": 5, "has_tech_stack": 0}	78	\N	\N	\N	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.686229	2026-08-25 17:29:16.686239	apollo	\N	\N	2
7af48211-0785-4db8-81bb-392a39c782ca	raphael.jamar@pmh.be	Raphael	Jamar	Chief Technology Officer (CTO)	Proximus Media House (PMH)	pmh.be	http://www.linkedin.com/in/raphaeljamar	60	media production		[]	Brussels	\N	\N	70	{"title": 25, "method": "rule_based", "industry": 8, "seniority": 10, "company_size": 22, "funding_stage": 5, "has_tech_stack": 0}	70	\N	\N	\N	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.689886	2026-08-25 17:29:16.689893	apollo	\N	\N	2
4facafe9-5b22-4316-8a73-66fd04d8fc92	mmisniakiewicz@ineog.pl	Michal	Misniakiewicz	Chief Technology Officer (CTO)	INEOGroup	ineogroup.pl	http://www.linkedin.com/in/micha%c5%82-mi%c5%9bniakiewicz-7b399083	55	information technology & services		[]	Warsaw	\N	\N	78	{"title": 25, "method": "rule_based", "industry": 16, "seniority": 10, "company_size": 22, "funding_stage": 5, "has_tech_stack": 0}	78	\N	\N	\N	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.693917	2026-08-25 17:29:16.693925	apollo	\N	\N	2
18b69bc0-37f7-4b4e-be0b-2b42441f683c	dario@adizes.com	Miguel	Magana Heredia	Chief Technology Officer CTO	Adizes Institute Worldwide	adizes.com	http://www.linkedin.com/in/dariomagana	150	management consulting		[]	Guadalajara	\N	\N	71	{"title": 25, "method": "rule_based", "industry": 9, "seniority": 10, "company_size": 22, "funding_stage": 5, "has_tech_stack": 0}	71	\N	\N	\N	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.697415	2026-08-25 17:29:16.697422	apollo	\N	\N	2
523ad45a-35ed-49ef-9db7-942273c14a3d	margoneto@publisys.it	Maurizio	Argoneto	Chief Technology Officer (CTO)	Publisys Spa	publisys.it	http://www.linkedin.com/in/argomauro	73	information technology & services		[]	Pignola	\N	\N	78	{"title": 25, "method": "rule_based", "industry": 16, "seniority": 10, "company_size": 22, "funding_stage": 5, "has_tech_stack": 0}	78	\N	\N	\N	0	f	t	t	2026-07-28 05:55:19	2026-07-28 05:55:19	2026-08-25 17:29:16.702009	2026-08-25 17:29:16.702017	apollo	\N	\N	2
\.


--
-- Data for Name: conversation_threads; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.conversation_threads (id, contact_id, outreach_log_id, event_type, direction, channel, content, subject, intent, intent_confidence, readiness_score_delta, readiness_score_after, draft_generated, draft_content, slack_message_ts, approved_by, approved_at, sent_at, occurred_at, rejected_by, rejected_at) FROM stdin;
9f6fd865-c816-48d5-ab39-3f345846c8e7	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	email_sent	outbound	email	Hi Sarah, congrats on the Series B. Teams scaling post-funding usually hit outbound bottlenecks fast. Worth 20 mins?	\N	\N	\N	0	0	f	\N	\N	\N	\N	\N	2026-08-23 01:29:15.870722	\N	\N
1aaa474d-9030-440e-9a27-b9fba0f5d951	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	reply_received	inbound	email	Thanks! Yes we're feeling growing pains. What does your platform do exactly?	\N	interested	0.85	25	25	f	\N	\N	\N	\N	\N	2026-08-24 21:29:15.871182	\N	\N
be343539-d9e9-4a8a-8b9d-a9c20817e928	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	email_sent	outbound	email	7 AI agents — prospecting, signals, outreach, CRM, content, forecasting. 3-day setup. Free demo Thursday?	\N	\N	\N	0	25	f	\N	\N	\N	\N	\N	2026-08-22 20:29:15.871337	\N	\N
63d5a4db-497f-4750-b7f9-e5f92069095e	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	reply_received	inbound	email	Thursday 2pm PST works. Send a cal link?	\N	interested	0.92	20	45	f	\N	\N	\N	\N	\N	2026-08-23 10:29:15.871479	\N	\N
44089db8-12be-44c7-999d-16482774a2bc	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	email_sent	outbound	email	Marcus — saw you joined ScalePath as CRO. New leaders usually audit the GTM stack in first 60 days. AI tooling on your list?	\N	\N	\N	0	0	f	\N	\N	\N	\N	\N	2026-08-25 02:29:15.871685	\N	\N
3d110f51-45b4-42cd-af6e-5d2901b8c0f0	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	reply_received	inbound	email	Actually yes. We're evaluating outbound stack right now. Send me a one-pager?	\N	interested	0.78	25	25	f	\N	\N	\N	\N	\N	2026-08-25 05:29:15.871815	\N	\N
700ee30d-cb1b-4e9a-b422-2aca9253b6b0	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	email_sent	outbound	email	Tom — noticed DataBridge switched from HubSpot to Salesforce. That transition is when teams re-evaluate everything.	\N	\N	\N	0	0	f	\N	\N	\N	\N	\N	2026-08-22 21:29:15.871965	\N	\N
d587bb6b-dd05-43c3-9c1c-97d190b6f1a5	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	reply_received	inbound	email	Good timing. We're in the middle of that chaos. What do you offer?	\N	interested	0.81	25	25	f	\N	\N	\N	\N	\N	2026-08-25 02:29:15.87206	\N	\N
6552f8de-a077-4a47-be4a-59cd33e6d767	08f266c6-0bb0-4adb-b7f4-555d52ecf565	\N	email_sent	outbound	email	Hi Lauren, noticed Galvin Technologies is scaling your Salesforce team in Q3. Outbound reps often lose hours building lists manually. Would a 15-min demo of our GTM automation platform be helpful next Tuesday at 2pm?	\N	\N	0	0	10	f	\N	\N	\N	\N	\N	2026-08-23 03:29:16.812975	\N	\N
a61c59aa-207c-4c69-adcc-dc6042ba94ea	08f266c6-0bb0-4adb-b7f4-555d52ecf565	\N	reply_received	inbound	email	Hi, thanks for reaching out. Yes, we actually have a demo call scheduled, but we are a bit worried about compliance and budget.	\N	interested	0.88	25	35	f	\N	\N	\N	\N	\N	2026-08-25 06:29:16.813256	\N	\N
2b25f277-3fff-4321-8665-5e810cfec066	08f266c6-0bb0-4adb-b7f4-555d52ecf565	\N	email_sent	outbound	email	Hi Lauren, completely understand. We support isolated European tenant deployment for full compliance. Let's discuss pricing on our call this Thursday at 2pm.	\N	\N	0	0	35	f	\N	\N	\N	\N	\N	2026-08-24 14:29:16.813478	\N	\N
\.


--
-- Data for Name: deal_stage_history; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.deal_stage_history (id, deal_id, from_stage, to_stage, days_in_from_stage, transitioned_at) FROM stdin;
81d6efe3-c92a-4230-b563-1c431f8c3e9b	2e096069-048c-4f37-9572-af501842a76e	prospecting	proposal	6	2026-08-17 17:29:16.178165
eb154ce2-468b-454d-b7b3-3c1c0ccf7263	2db3556b-711b-42c3-a8a9-344f88ed2480	prospecting	demo	3	2026-08-20 17:29:16.178469
20610f77-58da-416e-a567-f703399174ee	2cf3e44a-81dd-4cde-b8a9-dbacb6e2a956	prospecting	discovery	6	2026-08-13 17:29:16.178559
7eec6c96-d977-41d6-9bf3-aa6a40ed338f	0e5fe4ae-90e4-4745-9847-21a1ba1e546d	prospecting	negotiation	4	2026-08-06 17:29:16.178621
1753f475-2c5e-4e4b-b2f6-cbf0e1d7bcaf	e71bd37d-d9de-4a31-b183-67a1c5e240bb	prospecting	proposal	3	2026-08-02 17:29:16.178676
fb71562b-6f7c-49bd-b18c-d37839f9d660	66924626-8458-49c3-9fa4-af62fa436278	prospecting	prospecting	6	2026-08-22 17:29:16.178728
\.


--
-- Data for Name: deals; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.deals (id, hubspot_deal_id, contact_id, name, stage, amount, close_date, owner_email, days_in_current_stage, avg_response_time_hours, stakeholder_count, meeting_count, risk_flags, risk_score, budget_confirmed, authority_confirmed, need_confirmed, timeline_confirmed, outcome, lost_reason, stage_entered_at, created_at, updated_at, deal_health_score, win_probability, buying_intent, next_best_action, stage_confidence, objections) FROM stdin;
2e096069-048c-4f37-9572-af501842a76e	\N	5400a977-f9f0-43c4-9ca2-46317d7b8a25	GrowthOps — Platform Deal	proposal	24000	\N	rep@yourcompany.com	8	\N	1	0	[]	0.2	t	t	t	f	\N	\N	2026-08-17 17:29:16.089778	2026-08-25 17:29:16.103095	2026-08-25 17:29:16.103103	\N	\N	\N	\N	\N	\N
2db3556b-711b-42c3-a8a9-344f88ed2480	\N	1e79c123-e779-408a-bcf6-49936e2a62a6	ScalePath — Enterprise	demo	48000	\N	rep@yourcompany.com	5	\N	1	0	[]	0	t	f	t	f	\N	\N	2026-08-20 17:29:16.090155	2026-08-25 17:29:16.103119	2026-08-25 17:29:16.103122	\N	\N	\N	\N	\N	\N
2cf3e44a-81dd-4cde-b8a9-dbacb6e2a956	\N	2e81530f-14eb-4e6b-8c2f-14cee780d3e7	RevStack AI — Startup	discovery	9600	\N	rep@yourcompany.com	12	\N	1	0	[{"type": "stage_stall", "severity": "high", "description": "In discovery for 12 days — above average."}]	0.4	f	f	t	f	\N	\N	2026-08-13 17:29:16.090326	2026-08-25 17:29:16.103133	2026-08-25 17:29:16.103136	\N	\N	\N	\N	\N	\N
0e5fe4ae-90e4-4745-9847-21a1ba1e546d	\N	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	DataBridge — Pro Plan	negotiation	36000	\N	rep@yourcompany.com	19	\N	1	0	[{"type": "stage_stall", "severity": "high", "description": "In negotiation for 19 days — above average."}]	0.6	t	t	t	t	\N	\N	2026-08-06 17:29:16.090472	2026-08-25 17:29:16.103147	2026-08-25 17:29:16.10315	\N	\N	\N	\N	\N	\N
e71bd37d-d9de-4a31-b183-67a1c5e240bb	\N	caf9089c-85e9-4cba-8f79-c53ae6b26ced	PipelineCo — Growth	proposal	18000	\N	rep@yourcompany.com	23	\N	1	0	[{"type": "stage_stall", "severity": "high", "description": "In proposal for 23 days — above average."}]	0.5	t	f	t	f	\N	\N	2026-08-02 17:29:16.090602	2026-08-25 17:29:16.10316	2026-08-25 17:29:16.103163	\N	\N	\N	\N	\N	\N
66924626-8458-49c3-9fa4-af62fa436278	\N	45eb8c14-b33e-4710-8e6f-c0659dbecc25	SalesForge — Team Plan	prospecting	7200	\N	rep@yourcompany.com	3	\N	1	0	[]	0	f	f	f	f	\N	\N	2026-08-22 17:29:16.090688	2026-08-25 17:29:16.103173	2026-08-25 17:29:16.103176	\N	\N	\N	\N	\N	\N
f7243346-ddff-49e9-b94b-58a376bc5755	\N	08f266c6-0bb0-4adb-b7f4-555d52ecf565	Galvin Technologies — Demo and Pricing Review Call	demo	60000	\N	rep@yourcompany.com	5	\N	1	0	[]	0.1	f	f	f	f	\N	\N	2026-08-20 17:29:16.787462	2026-08-25 17:29:16.791911	2026-08-25 17:29:16.791921	\N	\N	\N	\N	\N	\N
\.


--
-- Data for Name: funnel_events; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.funnel_events (id, event_type, contact_id, deal_id, agent_id, event_metadata, "timestamp") FROM stdin;
00175394-4e9d-46ea-a0fb-8b1ae8f30bf6	prospect_batch_completed	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-07 21:29:16.280244
9ae21f58-db03-45df-8d3e-d1d996076d78	prospect_batch_completed	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-10 22:29:16.280589
87786a79-0c69-4f0c-9a42-7d42cbbbf8c0	prospect_batch_completed	\N	\N	A1	{"seeded": true}	2026-07-30 03:29:16.280783
ddcccd64-c5d9-488a-aafe-2a3415f35c37	prospect_batch_completed	\N	\N	A1	{"seeded": true}	2026-08-06 08:29:16.280937
dffc901c-0b87-42f0-aef8-afbfeca4bc1e	email_sent	010de45d-4272-462c-9f04-baf0115ad2ac	\N	A1	{"seeded": true}	2026-08-24 08:29:16.281057
afad559a-3476-4b16-ad53-30e6acc51a45	email_sent	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-08-08 02:29:16.281156
5ae42147-59b6-412a-9062-3d434398bfb7	email_sent	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-21 01:29:16.281246
6016ca61-68bc-4f71-8b1c-d47feb4ad6bf	email_sent	\N	\N	A1	{"seeded": true}	2026-08-19 02:29:16.281394
4d7fd6d6-91b2-49ba-b020-e4d78882ef6f	email_sent	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-09 04:29:16.281531
78a98b00-3645-442a-b18f-efe9e26838d1	email_sent	\N	\N	A1	{"seeded": true}	2026-08-10 19:29:16.281662
235f405e-f37e-4730-b748-3013eccc27af	email_sent	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-11 02:29:16.281914
21e28d5e-687d-455c-b206-099863507b3d	email_sent	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-08-02 09:29:16.28199
508a29d7-442c-4aab-9442-de2781e25a20	email_sent	b9befa8b-a1cc-4e22-af29-c90f0724f0c4	\N	A1	{"seeded": true}	2026-07-30 00:29:16.282076
9be8bba7-479c-47c6-98e1-20e5324c8e16	email_sent	2e81530f-14eb-4e6b-8c2f-14cee780d3e7	\N	A1	{"seeded": true}	2026-07-30 01:29:16.282252
2bb0f44f-d376-4e10-93fa-cd0c9bcd3a49	email_sent	\N	\N	A1	{"seeded": true}	2026-08-06 02:29:16.282323
3d551c9e-88e2-4be5-bee3-48d297b49578	email_sent	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-08-09 00:29:16.282384
6a76eba3-2c5b-45c7-b55e-4fbac7e2e108	email_sent	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-18 20:29:16.28244
15452f01-76e7-4ba9-b63c-a8604a9ceeb1	email_sent	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	A1	{"seeded": true}	2026-08-19 04:29:16.282497
83b7ced5-31da-438b-bbb8-13419c402cb0	email_sent	010de45d-4272-462c-9f04-baf0115ad2ac	\N	A1	{"seeded": true}	2026-07-29 20:29:16.282551
ed194faa-6708-4589-8a77-6b373aeda36b	email_sent	010de45d-4272-462c-9f04-baf0115ad2ac	\N	A1	{"seeded": true}	2026-08-12 06:29:16.282605
2201987f-f26c-494f-acd6-f6b9b3fc9595	email_sent	b9befa8b-a1cc-4e22-af29-c90f0724f0c4	\N	A1	{"seeded": true}	2026-08-12 00:29:16.282658
71d576e6-2973-4e54-9e2a-4fed1117f952	email_sent	\N	\N	A1	{"seeded": true}	2026-08-01 11:29:16.282712
1b8cfb41-6b12-4e88-b0d3-e63f8b3f9d1e	email_sent	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-01 03:29:16.282804
b2bfc139-8bf3-41ca-92b7-0446a66e969c	email_sent	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-12 03:29:16.28286
7f1fcf6f-caf6-482e-81d5-155966f0dfd7	email_sent	\N	\N	A1	{"seeded": true}	2026-08-18 16:29:16.282918
a004cedd-0d51-48b3-9ca4-5f6399ba8fc5	email_sent	010de45d-4272-462c-9f04-baf0115ad2ac	\N	A1	{"seeded": true}	2026-07-29 19:29:16.282969
4730e960-7e3c-4e1a-8a4f-9fb23da8614a	email_sent	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	A1	{"seeded": true}	2026-08-13 06:29:16.283028
37fe9c3f-e2d1-43a9-aaa2-751496af003b	email_sent	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-01 00:29:16.283101
c2796657-968d-4675-b21f-161b5b863194	email_sent	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-08-11 01:29:16.283162
6c80d2f6-ebdc-492f-a151-8d4cc627527e	email_sent	010de45d-4272-462c-9f04-baf0115ad2ac	\N	A1	{"seeded": true}	2026-07-29 11:29:16.283213
33e8ae90-2cc6-485d-8569-e94f07a55c38	email_sent	25ad487a-284d-49ce-aae0-a9edb5261b91	\N	A1	{"seeded": true}	2026-08-05 12:29:16.283313
b04a2069-c8dd-452c-a072-55540bcde8ee	email_sent	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-16 19:29:16.283406
7da3f88b-ced6-44d6-8931-74e0ac9b5c8c	email_sent	25ad487a-284d-49ce-aae0-a9edb5261b91	\N	A1	{"seeded": true}	2026-08-01 12:29:16.28352
865e1558-1653-49ae-b339-97d070d5745f	email_sent	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-07-30 01:29:16.283589
e6bc9835-5540-4da0-ac27-0074e85db746	email_sent	\N	\N	A1	{"seeded": true}	2026-08-02 05:29:16.283654
3611e066-442a-4c37-b35f-b17468636d25	email_sent	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-08-07 06:29:16.283708
b9076cb7-9be7-42c7-9794-dc7749d13b86	email_sent	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-08-03 17:29:16.283758
0b4b3293-7909-4410-8edb-2b4cc369e12f	email_sent	010de45d-4272-462c-9f04-baf0115ad2ac	\N	A1	{"seeded": true}	2026-08-02 22:29:16.283809
e5d5d3f9-414d-4f93-8552-d7b4e55f8ea8	email_sent	2e81530f-14eb-4e6b-8c2f-14cee780d3e7	\N	A1	{"seeded": true}	2026-08-18 04:29:16.283858
5ae74724-f91b-408a-acec-b71137f35f3c	email_sent	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-24 22:29:16.283908
b93ee077-68a9-4c4f-8619-eb03c818fd80	email_sent	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-08-16 12:29:16.283966
361ff834-e0b2-4a15-902f-93d1cb5cb43c	email_sent	010de45d-4272-462c-9f04-baf0115ad2ac	\N	A1	{"seeded": true}	2026-08-12 21:29:16.284016
65104d9e-7c4c-4e90-a5ab-e2d3b3989049	email_sent	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-22 00:29:16.284067
3a499c52-1094-464f-8ae0-26ea69ef39ea	email_sent	25ad487a-284d-49ce-aae0-a9edb5261b91	\N	A1	{"seeded": true}	2026-08-11 08:29:16.284118
d999013a-72a0-434d-a619-bd624a6c3491	email_sent	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-08-24 10:29:16.284171
3a6a3cef-a705-43f9-85fa-b4ed137f7f46	email_sent	\N	\N	A1	{"seeded": true}	2026-08-24 18:29:16.28422
d77cb9da-4bf8-476c-82d5-45b4ed27b78e	email_sent	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-08-06 05:29:16.284272
c991cb02-8fca-43b1-b36d-fe9f3f83bb30	email_sent	2e81530f-14eb-4e6b-8c2f-14cee780d3e7	\N	A1	{"seeded": true}	2026-08-21 01:29:16.284333
96c72b05-7c7e-46c6-b991-94472bf7cff8	email_sent	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-08-17 05:29:16.284391
37cad0fc-ed59-4b6a-8de6-457c586e8ded	email_sent	25ad487a-284d-49ce-aae0-a9edb5261b91	\N	A1	{"seeded": true}	2026-08-08 23:29:16.284623
f7ff0663-fc43-474e-8a5b-cbb873265903	email_sent	01636f82-ee99-4e99-9bba-e92a3af40853	\N	A1	{"seeded": true}	2026-07-31 20:29:16.284684
9c4dba7e-519d-4084-8b9b-c71b35deb80e	email_sent	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	A1	{"seeded": true}	2026-08-17 02:29:16.284737
4355f296-0dcb-4a93-90b3-54bc6ca3b355	email_sent	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-07-31 19:29:16.284788
43605d8b-b796-4940-830b-a8d0b67277b1	email_sent	01636f82-ee99-4e99-9bba-e92a3af40853	\N	A1	{"seeded": true}	2026-08-06 04:29:16.284837
b8ce19ec-5e0b-4335-99c6-a726d663293e	email_sent	\N	\N	A1	{"seeded": true}	2026-08-21 20:29:16.2849
4f8a741d-d1ef-45d5-b688-2910b5eea29d	email_sent	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-08-17 12:29:16.284952
62eda9f0-4a0b-453f-be39-ecf7444fca9c	email_sent	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-20 16:29:16.285009
267896ff-d44e-4aaf-8c02-d65706b51168	email_sent	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-10 13:29:16.285058
d2a4cfee-2308-4a03-b95c-06a36d90ba07	email_draft_created	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-08-02 04:29:16.285109
c022d125-6c2a-4f14-bbc9-724fe748d23b	email_draft_created	\N	\N	A1	{"seeded": true}	2026-08-01 18:29:16.285158
1a9f6aa1-adb7-404f-805a-2efbfc3d2082	email_draft_created	\N	\N	A1	{"seeded": true}	2026-08-20 10:29:16.285377
de568b37-cbd9-442f-8aff-ede84b7d7314	email_draft_created	b9befa8b-a1cc-4e22-af29-c90f0724f0c4	\N	A1	{"seeded": true}	2026-08-07 12:29:16.285631
540b2b2f-57c1-4c75-8ec3-05314e11e521	email_draft_created	01636f82-ee99-4e99-9bba-e92a3af40853	\N	A1	{"seeded": true}	2026-07-29 10:29:16.285989
a15fdfea-f080-4761-9fd8-a3217b15a7b5	email_draft_created	01636f82-ee99-4e99-9bba-e92a3af40853	\N	A1	{"seeded": true}	2026-08-04 15:29:16.286109
018d9382-a1dc-4859-b725-27a28340a1f5	email_draft_created	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-23 03:29:16.286193
a845d2ac-01ee-4513-8a2e-1567757b2b56	email_draft_created	010de45d-4272-462c-9f04-baf0115ad2ac	\N	A1	{"seeded": true}	2026-08-12 01:29:16.286265
3eaee038-3bed-4a1f-a4b8-2134e532e15e	email_draft_created	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-08-03 14:29:16.286356
b58e8458-0474-4638-b535-10a91a9bb7a8	email_draft_created	\N	\N	A1	{"seeded": true}	2026-08-09 14:29:16.286425
59453cd1-53b4-4384-813f-fbba441e6f96	email_draft_created	01636f82-ee99-4e99-9bba-e92a3af40853	\N	A1	{"seeded": true}	2026-08-19 10:29:16.286499
90bf1832-210d-4d62-9bb3-8e5b25ec0077	email_draft_created	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-08 02:29:16.286567
e887a2d9-6ced-477b-9671-0e25c42971c1	signal_batch_completed	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-14 08:29:16.286621
27ec98e3-de11-4ca6-b61a-532d235ef441	signal_batch_completed	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-07-29 06:29:16.286681
b99381f7-8895-4df1-877e-a60702386f4f	signal_batch_completed	\N	\N	A1	{"seeded": true}	2026-08-07 08:29:16.28673
39a5be75-4a33-4fa4-a38e-c964c5a275ff	signal_batch_completed	\N	\N	A1	{"seeded": true}	2026-08-18 20:29:16.286787
53d812e2-74e6-4da3-a830-7794f78e71e4	signal_batch_completed	\N	\N	A1	{"seeded": true}	2026-07-30 11:29:16.286856
c8f956b6-1711-447d-a3ba-7588c1b81029	signal_batch_completed	\N	\N	A1	{"seeded": true}	2026-08-23 06:29:16.286905
28c7abe8-1402-4c0b-9f44-9a411f42f446	signal_batch_completed	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	A1	{"seeded": true}	2026-08-16 14:29:16.287042
e9538591-7591-4f12-b386-ef37dd3d98e4	signal_batch_completed	01636f82-ee99-4e99-9bba-e92a3af40853	\N	A1	{"seeded": true}	2026-08-09 17:29:16.287116
9e083d76-4b5c-487d-9fec-43d5c0db7955	signal_batch_completed	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-03 02:29:16.287317
a06c7a8b-5cd5-4f91-96f8-2184446b0b18	signal_batch_completed	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-12 20:29:16.287509
87a2634e-c070-4770-bd16-0e94180bd868	signal_batch_completed	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-08-08 16:29:16.287607
b2c84298-2918-4f6a-a89a-126b6a2f2506	signal_batch_completed	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-08-13 13:29:16.287714
51f41393-2a7b-45fd-a7fd-9ce29071765a	signal_batch_completed	\N	\N	A1	{"seeded": true}	2026-08-07 21:29:16.287808
2289a4d5-e87b-4b54-b246-f6c6a078a3ad	signal_batch_completed	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	A1	{"seeded": true}	2026-08-17 21:29:16.287903
45f97814-c675-4509-ab29-ad5ddfe84b9e	signal_batch_completed	\N	\N	A1	{"seeded": true}	2026-08-21 20:29:16.287986
1bd9c2ae-328e-4ede-8ca1-b4671f0e2a16	signal_batch_completed	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-25 13:29:16.28807
8edf639f-a399-4f35-8a19-d2560730704a	signal_batch_completed	b9befa8b-a1cc-4e22-af29-c90f0724f0c4	\N	A1	{"seeded": true}	2026-08-11 12:29:16.288185
913e7979-d352-4a12-bfcd-d288dca3c605	signal_batch_completed	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-07-31 18:29:16.288269
e593e879-ff9b-4fd0-8a14-4bfcc6c225f5	reply_received	\N	\N	A1	{"seeded": true}	2026-08-20 06:29:16.28834
dc81e9ae-151b-4656-bd31-761ba978877a	reply_received	2e81530f-14eb-4e6b-8c2f-14cee780d3e7	\N	A1	{"seeded": true}	2026-07-30 00:29:16.288427
0444fe6e-900a-48fe-abc7-981b7234252c	reply_received	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	A1	{"seeded": true}	2026-08-19 09:29:16.288498
421c6f77-0b87-4560-8f6e-788a6720b1eb	reply_received	01636f82-ee99-4e99-9bba-e92a3af40853	\N	A1	{"seeded": true}	2026-08-18 00:29:16.288571
6141129d-ee7f-4341-80cd-d0dbd350765c	reply_received	b9befa8b-a1cc-4e22-af29-c90f0724f0c4	\N	A1	{"seeded": true}	2026-08-22 01:29:16.288661
3aab0df3-1e10-4fac-bf9e-4d9f20d44634	reply_received	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-08-22 05:29:16.288741
232df05c-f5c2-43aa-a24e-7a857eaf67ee	reply_received	b9befa8b-a1cc-4e22-af29-c90f0724f0c4	\N	A1	{"seeded": true}	2026-08-02 22:29:16.28881
88bfcddf-762b-4d6c-b154-ace4e2cda505	reply_received	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-23 12:29:16.288883
4f0a81b3-7281-4844-8b0d-e927a324aaab	reply_received	\N	\N	A1	{"seeded": true}	2026-08-18 05:29:16.289003
cab93b88-e257-48eb-a996-641a68b3e536	reply_received	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-07-28 18:29:16.28912
9463112b-619e-48d7-becd-39b9a3c6d89b	reply_received	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-01 20:29:16.289219
7fd3065f-0d5c-42f5-abb9-979b72041a95	reply_received	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-07-28 04:29:16.289305
89c15b4e-3ce1-4720-b763-198dec994e6c	reply_received	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-21 19:29:16.289382
be7652fb-ad82-4894-8d75-8e38d7851ddc	reply_received	\N	\N	A1	{"seeded": true}	2026-08-04 21:29:16.289452
47f3a133-5185-4110-9f42-ce576770adf2	reply_received	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-07-30 14:29:16.289539
02ae4896-a283-4b8e-ac39-c4648ed526a9	reply_received	\N	\N	A1	{"seeded": true}	2026-08-03 12:29:16.289808
71170144-9459-4cea-86a9-e4f6dfb7d53f	reply_received	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-08-07 03:29:16.289931
2e713ae0-8ea2-4b30-9e75-d0c9cbabde2a	reply_received	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	A1	{"seeded": true}	2026-07-29 07:29:16.290025
a2706c73-1ee0-4743-a041-4473282d873a	meeting_booked	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	A1	{"seeded": true}	2026-08-20 07:29:16.290103
0c443af0-449e-4eb2-a8db-0ab9865d107f	meeting_booked	\N	\N	A1	{"seeded": true}	2026-08-01 12:29:16.290176
876513b9-a5a6-48ff-9d49-0944ad7ed311	meeting_booked	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-08-20 12:29:16.290247
4f3770a3-8f72-4ee9-98bd-ccd602645df4	meeting_booked	b9befa8b-a1cc-4e22-af29-c90f0724f0c4	\N	A1	{"seeded": true}	2026-08-02 05:29:16.290329
440de10b-95b4-4ff9-8594-172635bec177	meeting_booked	2e81530f-14eb-4e6b-8c2f-14cee780d3e7	\N	A1	{"seeded": true}	2026-08-23 23:29:16.290422
62c30b1c-8061-404b-8018-b6732c588f7e	meeting_booked	25ad487a-284d-49ce-aae0-a9edb5261b91	\N	A1	{"seeded": true}	2026-08-07 01:29:16.290511
f287c284-6bbd-4929-a781-6a3cdbde6c3f	meeting_booked	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-08-24 14:29:16.290583
da6b05c8-b133-4ad2-ace9-b6fc4e45747b	meeting_booked	\N	\N	A1	{"seeded": true}	2026-08-05 19:29:16.290653
2889a021-8b35-4e88-974c-36e7b5741b27	meeting_booked	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	A1	{"seeded": true}	2026-08-18 08:29:16.290735
2166c7e4-3819-4cff-a552-c2947b50997f	transcript_processed	\N	\N	A1	{"seeded": true}	2026-07-28 04:29:16.290821
0ee81230-48f9-4e84-ad38-d327e80bbe9f	transcript_processed	\N	\N	A1	{"seeded": true}	2026-07-29 08:29:16.290889
5260015a-fe64-472a-b099-5b01d67cdd2f	transcript_processed	2e81530f-14eb-4e6b-8c2f-14cee780d3e7	\N	A1	{"seeded": true}	2026-07-28 10:29:16.291068
30f7b307-751e-4494-893f-b91b4309024c	transcript_processed	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	A1	{"seeded": true}	2026-08-21 04:29:16.291179
10c9a969-bcdc-4df6-8619-fa17e7aee37e	transcript_processed	25ad487a-284d-49ce-aae0-a9edb5261b91	\N	A1	{"seeded": true}	2026-07-29 06:29:16.29127
056e4407-d7e8-4700-86f2-65d9824e2d16	transcript_processed	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	A1	{"seeded": true}	2026-08-23 12:29:16.291365
da85e413-e6ac-42e7-bc90-83d51c3d7dea	content_batch_completed	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	A1	{"seeded": true}	2026-08-18 12:29:16.291445
c5684790-49a0-4fb5-98a7-8632fc2b5741	content_batch_completed	\N	\N	A1	{"seeded": true}	2026-08-23 06:29:16.291517
b48f70a8-abfe-4388-80f2-d8f1256ac26f	content_batch_completed	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	A1	{"seeded": true}	2026-08-08 19:29:16.291588
37935408-5dbb-4f5f-a121-1d03b3c4de44	forecast_calculated	\N	\N	A1	{"seeded": true}	2026-08-21 23:29:16.291666
9028a345-480a-45c9-a1fd-ed17fa7cc349	forecast_calculated	\N	\N	A1	{"seeded": true}	2026-08-07 06:29:16.291734
cd2b8f97-03f1-45c0-a92d-2a37d58f354c	signal_batch_completed	\N	\N	A2	{"reason": "Saved 9 new buying signal(s)", "signals_saved": 9, "contacts_scanned": 25, "contacts_updated": 8, "signals_detected": 9}	2026-08-26 04:56:45.161906
f011e985-1530-4eda-a5af-b118de29141b	outreach_batch_completed	\N	\N	A3	{"sent": 0, "drafts": 3, "processed": 9, "skip_reasons": {"send_failed": 0, "deduplicated": 6, "invalid_email": 0, "missing_email": 0, "do_not_contact": 0, "inactive_session": 0, "generation_failed": 0, "sequence_completed": 0, "decision_engine_rejected": 0, "icp_score_below_threshold": 0, "missing_contact_or_signal": 0, "signal_score_below_threshold": 0}}	2026-08-26 04:59:01.971649
65f91664-a9c3-44a9-9afb-b3f5cd4e3a24	signal_batch_completed	\N	\N	A2	{"reason": "Signals were detected but all were duplicates inside the dedupe window", "signals_saved": 0, "contacts_scanned": 25, "contacts_updated": 2, "signals_detected": 3}	2026-08-26 05:01:37.936005
b0defda7-ac44-484a-a6ae-136c309059b4	outreach_batch_completed	\N	\N	A3	{"sent": 0, "drafts": 0, "processed": 9, "skip_reasons": {"send_failed": 0, "deduplicated": 9, "invalid_email": 0, "missing_email": 0, "do_not_contact": 0, "inactive_session": 0, "generation_failed": 0, "sequence_completed": 0, "decision_engine_rejected": 0, "icp_score_below_threshold": 0, "missing_contact_or_signal": 0, "signal_score_below_threshold": 0}}	2026-08-26 05:01:39.295968
27786978-2f6e-4819-b24c-f61d2610e55c	signal_batch_completed	\N	\N	A2	{"reason": "Signals were detected but all were duplicates inside the dedupe window", "signals_saved": 0, "contacts_scanned": 25, "contacts_updated": 1, "signals_detected": 1}	2026-08-26 06:03:06.870003
64677c3f-2af0-4e74-8b99-29087a91e2f8	signal_batch_completed	\N	\N	A2	{"reason": "Signals were detected but all were duplicates inside the dedupe window", "signals_saved": 0, "contacts_scanned": 25, "contacts_updated": 6, "signals_detected": 6}	2026-08-26 07:01:30.566205
\.


--
-- Data for Name: generated_content; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.generated_content (id, title, content_format, icp_segment, topic, content, brief, engagement_score, used_in_outreach, published, created_at) FROM stdin;
1edd41da-b455-44ae-8776-8c7f0e798f0f	Why B2B Outbound Fails — LinkedIn Post	linkedin_post	B2B SaaS	Why B2B Outbound Fails — LinkedIn Post	Most B2B outbound fails for one reason: teams send the same email to everyone.\n\nThe company that just raised a Series B has completely different problems than the one at seed stage.\n\nPersonalization is matching your message to the specific moment they're in.\n\nWhat moment is your prospect in right now?	\N	0	f	f	2026-08-25 17:29:16.433429
ab9e12bb-739c-47b9-ab6a-1c195ff48cbb	How Series B Companies Scale GTM Without Hiring — Blog	blog_article	Series B SaaS	How Series B Companies Scale GTM Without Hiring — Blog	The funding is in the bank. The board wants 3x growth. The instinct is to hire.\n\nBut the fastest-growing B2B SaaS companies at Series B aren't just hiring more reps. They're building systems that make each rep dramatically more effective.\n\nHere is what that looks like in practice...	\N	0	f	f	2026-08-25 17:29:16.433449
d81f678e-439d-4a2d-90be-aba1a715927f	Email Sequence — New VP Hire Signal	email_sequence	Sales Technology	Email Sequence — New VP Hire Signal	Email 1 (Day 2):\nSubject: Congrats on the new role\n\nHi {first_name},\n\nSaw you joined {company} as {title} — congrats. New sales leaders typically audit tools in the first 60 days. AI agents on your radar?\n\n{sender}	\N	0	t	f	2026-08-25 17:29:16.433461
\.


--
-- Data for Name: outreach_drafts; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.outreach_drafts (id, contact_id, signal_id, subject, body, business_case, matched_services, channel, status, approval_state, created_at, updated_at) FROM stdin;
138b331d-f4ea-4922-b304-1b03e28a2a68	25ad487a-284d-49ce-aae0-a9edb5261b91	1b32f59d-de3a-4392-b1a9-22d1f9ff36b9	Streamlining CRM & GTM at Outbound AI post-Series A	Hi Rachel,\n\nI’m reaching out because we help AI SaaS companies like Outbound AI automate GTM operations and integrate cloud CRM systems—critical for scaling post-Series A.\n\nWith your recent $5.5M raise, I wanted to see how you’re currently handling Salesforce data enrichment and lead enrichment to support your growth.\n\nDo you have 10 minutes for a quick chat?\n\nBest,\n[Your Name]	General Sales Outreach	["GTM automation", "Salesforce integration", "CRM consulting"]	email	pending	pending	2026-08-26 04:57:35.343857	2026-08-26 04:57:35.34387
6ee1db1b-a28e-4cf7-85af-aa21fdf30bda	01636f82-ee99-4e99-9bba-e92a3af40853	5087f5ff-d71d-4650-96d4-ec7f8f4c3e1e	Helping Metrics360 scale its SDR and BDR team	Hi David,\n\nI noticed that Metrics360 is currently expanding and hiring several new SDRs and BDRs. Building out and ramping a high-performing sales team at this stage can quickly become an operational bottleneck.\n\nWe specialize in Salesforce integration and CRM automation to help scale sales operations. I wanted to see if you have considered automating parts of your onboarding and lead routing flows to free up your new reps' time to sell?\n\nBest,\n[Your Name]	Recruitment Partnership	["GTM automation", "Salesforce integration", "CRM consulting"]	email	pending	pending	2026-08-26 04:58:34.135388	2026-08-26 04:58:34.135401
b1bc285f-6dd7-45c5-a831-4748395ccbe3	45eb8c14-b33e-4710-8e6f-c0659dbecc25	abaa9768-2b47-477d-a9e2-c67216f29c02	Helping SalesForge scale its B2B sales team	Hi James,\n\nI noticed SalesForge is hiring for a B2B technology sales rep with uncapped commission and residual income—a great sign of growth. Scaling a high-performing sales team at this stage can be a real bottleneck, especially with ramp time and productivity.\n\nWe specialize in Salesforce integration and CRM automation to help sales teams hit the ground running. Have you considered automating parts of your onboarding flow to get your new reps producing faster?\n\nBest,\n[Your Name]	Recruitment Partnership	["GTM automation", "CRM consulting", "Salesforce integration"]	email	pending	pending	2026-08-26 04:59:01.763041	2026-08-26 04:59:01.763053
\.


--
-- Data for Name: outreach_log; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.outreach_log (id, contact_id, campaign_id, campaign_type, channel, subject, body_preview, prompt_variant_id, signal_id, outreach_provider_message_id, opened, open_count, replied, meeting_booked, unsubscribed, bounced, sent_at, replied_at, sequence_step, call_script, linkedin_note) FROM stdin;
1bb95182-8f42-484c-8b4c-98f3cf8fd7c4	5400a977-f9f0-43c4-9ca2-46317d7b8a25	\N	funding_round	email	Quick question about GrowthOps's growth	Hi Sarah, noticed GrowthOps has been making moves recently...	funding_v1	ea0bd3d5-6123-4e82-90c7-de1a45a0ceb0	\N	t	1	t	t	f	f	2026-08-17 17:29:15.732072	2026-08-23 17:29:15.732143	0	\N	\N
1b45cc57-670f-46a5-8efe-0498ae54e40e	1e79c123-e779-408a-bcf6-49936e2a62a6	\N	new_hire	email	Quick question about ScalePath's growth	Hi Marcus, noticed ScalePath has been making moves recently...	funding_v1	40cce2e4-4b24-4325-bf45-2c6512bf18c1	\N	t	1	t	f	f	f	2026-08-15 17:29:15.732513	2026-08-24 17:29:15.732533	0	\N	\N
1d2c306d-4ca2-4dc6-a4a2-662b90a553b3	2e81530f-14eb-4e6b-8c2f-14cee780d3e7	\N	job_posting	email	Quick question about RevStack AI's growth	Hi Priya, noticed RevStack AI has been making moves recently...	newhire_v1	ba2fd640-79a2-4b73-90be-12ce091da703	\N	t	1	t	f	f	f	2026-08-22 17:29:15.732642	2026-08-23 17:29:15.732655	0	\N	\N
9988a104-fd64-4a8a-9c9d-2c7c5ddd689e	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	\N	tech_stack_change	email	Quick question about DataBridge's growth	Hi Tom, noticed DataBridge has been making moves recently...	newhire_v1	13d01749-4524-4534-bfe1-3e82a8f10fc2	\N	t	1	f	f	f	f	2026-08-15 17:29:15.732742	\N	0	\N	\N
05293d34-4dc4-45f8-9c4f-260c44a1d1b6	caf9089c-85e9-4cba-8f79-c53ae6b26ced	\N	funding_round	email	Quick question about PipelineCo's growth	Hi Lisa, noticed PipelineCo has been making moves recently...	newhire_v1	677fe05b-e91d-43f7-b0b0-22406f4ab4b0	\N	t	1	f	f	f	f	2026-08-24 17:29:15.732844	\N	0	\N	\N
23f721d9-286c-48b0-8da6-cc737625849b	45eb8c14-b33e-4710-8e6f-c0659dbecc25	\N	new_hire	email	Quick question about SalesForge's growth	Hi James, noticed SalesForge has been making moves recently...	newhire_v1	20d4f36e-53ca-4763-9f1f-84bd5e1077e7	\N	f	0	f	f	f	f	2026-08-22 17:29:15.733117	\N	0	\N	\N
cbcc01ec-76ed-4454-8bea-23467d78455e	b9befa8b-a1cc-4e22-af29-c90f0724f0c4	\N	news_expansion	email	Quick question about GrowthLeap's growth	Hi Anna, noticed GrowthLeap has been making moves recently...	newhire_v1	fdf9d3bf-cd3f-4e00-85bb-69d8a0f0da65	\N	f	0	f	f	f	f	2026-08-11 17:29:15.733326	\N	0	\N	\N
\.


--
-- Data for Name: pending_actions; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.pending_actions (id, action_type, entity_type, entity_id, recommended_value, current_value, reason, agent_id, status, slack_message_ts, approved_by, created_at, approved_at, expires_at) FROM stdin;
072f930b-ce63-425d-ba4d-787b79c0f2a2	stage_stall	deal	0e5fe4ae-90e4-4745-9847-21a1ba1e546d	Move to closed_won or re-qualify	negotiation	In negotiation 19d — avg is 9d.	A5	pending	\N	\N	2026-08-25 17:29:16.26303	\N	2026-08-28 17:29:16.259594
244f24ff-d5bf-4cea-80c5-48fae8d8f6e5	incomplete_bant	deal	2db3556b-711b-42c3-a8a9-344f88ed2480	Confirm authority before next call	demo	Authority not confirmed at demo stage.	A5	pending	\N	\N	2026-08-25 17:29:16.263064	\N	2026-08-28 17:29:16.259957
2d2a6ca3-067a-40b0-b87d-b40027a66674	stage_stall	deal	e71bd37d-d9de-4a31-b183-67a1c5e240bb	Set explicit decision deadline	proposal	In proposal 23d without agreement.	A5	pending	\N	\N	2026-08-25 17:29:16.263105	\N	2026-08-28 17:29:16.260046
80edceee-9e81-4957-bf13-190468573091	response_slowdown	deal	2cf3e44a-81dd-4cde-b8a9-dbacb6e2a956	Try a different stakeholder	discovery	Response time grew 24h → 72h over last 3 touches.	A5	pending	\N	\N	2026-08-25 17:29:16.263136	\N	2026-08-28 17:29:16.260125
2149bffd-cdbf-4ff0-8df3-7280bfa11a7c	approve_outreach	contact	25ad487a-284d-49ce-aae0-a9edb5261b91	Streamlining CRM & GTM at Outbound AI post-Series A	draft	Review A3 draft for rachel.green@outbound.ai. Business Case: General Sales Outreach	A3	pending	\N	\N	2026-08-26 04:57:35.418809	\N	\N
bf1bcec2-33dc-4e01-8f12-8aa10718cceb	approve_outreach	contact	01636f82-ee99-4e99-9bba-e92a3af40853	Helping Metrics360 scale its SDR and BDR team	draft	Review A3 draft for david.kim@metrics360.com. Business Case: Recruitment Partnership	A3	pending	\N	\N	2026-08-26 04:58:34.230665	\N	\N
c103eac2-7d5c-4e84-b265-70e1483d8e27	approve_outreach	contact	45eb8c14-b33e-4710-8e6f-c0659dbecc25	Helping SalesForge scale its B2B sales team	draft	Review A3 draft for james.miller@salesforge.com. Business Case: Recruitment Partnership	A3	pending	\N	\N	2026-08-26 04:59:01.767124	\N	\N
\.


--
-- Data for Name: prompt_variants; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.prompt_variants (id, signal_type, channel, system_prompt, user_prompt_template, reply_rate, send_count, reply_count, meeting_count, is_active, created_at, updated_at) FROM stdin;
funding_v1	funding_round	email	Write concise B2B cold emails for SignalType.FUNDING_ROUND signals. Under 120 words.	Write to {{first_name}} at {{company}}. Signal: {{signal_type}}.	0.148	81	12	4	t	2026-08-25 17:29:15.697288	2026-08-25 17:29:15.697297
newhire_v1	new_hire	email	Write concise B2B cold emails for SignalType.NEW_HIRE signals. Under 120 words.	Write to {{first_name}} at {{company}}. Signal: {{signal_type}}.	0.112	62	7	2	t	2026-08-25 17:29:15.697301	2026-08-25 17:29:15.697304
jobpost_v1	job_posting	email	Write concise B2B cold emails for SignalType.JOB_POSTING signals. Under 120 words.	Write to {{first_name}} at {{company}}. Signal: {{signal_type}}.	0.078	103	8	2	t	2026-08-25 17:29:15.697307	2026-08-25 17:29:15.69731
\.


--
-- Data for Name: revenue_forecasts; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.revenue_forecasts (id, forecast_30d, forecast_60d, forecast_90d, current_pipeline_value, bottleneck_stage, bottleneck_description, recommended_lever, stage_conversion_rates, stage_velocity_days, calculated_at) FROM stdin;
9050398f-74b4-4c6f-8b58-f3138ee02141	31416	72828	105672	142800	proposal	Proposal conversion 28% vs 41% historical baseline. 2 deals stalled >20 days.	Set explicit decision deadlines. Involve procurement earlier to prevent stalls.	{"demo_to_proposal": 0.44, "discovery_to_demo": 0.58, "proposal_to_negotiation": 0.28, "prospecting_to_discovery": 0.41, "negotiation_to_closed_won": 0.71}	{"demo": 5.1, "proposal": 16.4, "discovery": 7.8, "negotiation": 11.2, "prospecting": 4.2}	2026-08-25 13:29:16.470298
\.


--
-- Data for Name: signal_conversion_registry; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.signal_conversion_registry (id, signal_type, conversion_rate, sample_size, last_calibrated_at, created_at) FROM stdin;
9d05ffa4-d191-4a1e-85c8-bb7ae72884a9	tech_stack_change	0.72	34	2026-08-13 17:29:15.674295	2026-08-25 17:29:15.67829
34693798-fa13-48db-95a5-ea394d1a96ec	new_hire	0.61	52	2026-08-13 17:29:15.674654	2026-08-25 17:29:15.678306
87f284c9-980f-41c5-aa2a-90bf56169800	funding_round	0.58	41	2026-08-13 17:29:15.674759	2026-08-25 17:29:15.678317
fe6bcbd7-c6b7-4b4c-b6f6-969fb582d904	job_posting	0.43	67	2026-08-13 17:29:15.674813	2026-08-25 17:29:15.678329
770179fb-d2ed-4d3e-a16d-3710a28b6ede	earnings_call	0.64	18	2026-08-13 17:29:15.674855	2026-08-25 17:29:15.678339
c0c81615-3ba9-4f44-9f08-75e7e73f98f2	competitor_review	0.38	23	2026-08-13 17:29:15.674892	2026-08-25 17:29:15.678349
9020d61e-40b8-443a-b693-0dbfabab8992	news_expansion	0.22	29	2026-08-13 17:29:15.674929	2026-08-25 17:29:15.678358
6bdb3043-2261-42da-b182-43d7aca0aed6	social_engagement	0.14	45	2026-08-13 17:29:15.674965	2026-08-25 17:29:15.678368
\.


--
-- Data for Name: signal_events; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.signal_events (id, contact_id, signal_type, signal_source, confidence, conversion_weight, raw_data, processed, triggered_outreach, detected_at, sequence_step, next_step_due_at) FROM stdin;
ea0bd3d5-6123-4e82-90c7-de1a45a0ceb0	5400a977-f9f0-43c4-9ca2-46317d7b8a25	funding_round	newsapi_funding	0.6	0.6	{"headline": "GrowthOps raises $18M Series B", "round_type": "Series B", "amount_mentioned": "$18M"}	f	f	2026-08-25 14:29:15.52773	0	\N
40cce2e4-4b24-4325-bf45-2c6512bf18c1	1e79c123-e779-408a-bcf6-49936e2a62a6	new_hire	newsapi_general	0.65	0.65	{"trigger": "leadership_news", "headline": "ScalePath names new CRO"}	f	f	2026-08-24 18:29:15.528016	0	\N
ba2fd640-79a2-4b73-90be-12ce091da703	2e81530f-14eb-4e6b-8c2f-14cee780d3e7	job_posting	adzuna	0.45	0.45	{"roles": ["SDR Manager", "BDR Team Lead"], "job_count": 4}	f	f	2026-08-23 17:29:15.528124	0	\N
13d01749-4524-4534-bfe1-3e82a8f10fc2	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	tech_stack_change	website_fingerprint	0.75	0.75	{"added": ["Salesforce", "Gong"], "removed": ["HubSpot CRM"]}	f	f	2026-08-25 04:29:15.528202	0	\N
677fe05b-e91d-43f7-b0b0-22406f4ab4b0	caf9089c-85e9-4cba-8f79-c53ae6b26ced	funding_round	newsapi_funding	0.6	0.6	{"headline": "PipelineCo closes $9M Series A", "amount_mentioned": "$9M"}	f	f	2026-08-25 01:29:15.52829	0	\N
20d4f36e-53ca-4763-9f1f-84bd5e1077e7	45eb8c14-b33e-4710-8e6f-c0659dbecc25	new_hire	adzuna	0.65	0.65	{"roles": ["VP of Sales"], "trigger": "leadership_hire"}	f	f	2026-08-25 04:29:15.528392	0	\N
fdf9d3bf-cd3f-4e00-85bb-69d8a0f0da65	b9befa8b-a1cc-4e22-af29-c90f0724f0c4	news_expansion	newsapi_general	0.25	0.25	{"headline": "GrowthLeap expands to European markets"}	f	f	2026-08-24 19:29:15.528475	0	\N
5087f5ff-d71d-4650-96d4-ec7f8f4c3e1e	01636f82-ee99-4e99-9bba-e92a3af40853	job_posting	adzuna	0.45	0.45	{"roles": ["SDR", "BDR"], "job_count": 6}	f	f	2026-08-23 20:29:15.528544	0	\N
1b32f59d-de3a-4392-b1a9-22d1f9ff36b9	25ad487a-284d-49ce-aae0-a9edb5261b91	funding_round	newsapi_funding	0.6	0.6	{"headline": "Outbound AI secures $5.5M Series A", "amount_mentioned": "$5.5M"}	f	f	2026-08-24 03:29:15.528607	0	\N
19297364-005f-4865-aa16-0c7934f93c1e	08f266c6-0bb0-4adb-b7f4-555d52ecf565	funding_round	currents	0.9	0.9	{"headline": "Galvin Technologies raises $10M Series B to expand Salesforce automation offerings", "amount_mentioned": "$10M"}	t	t	2026-08-23 17:29:16.851317	0	\N
a3e3d267-dadf-45c3-9cfb-6ff5777b92c5	01636f82-ee99-4e99-9bba-e92a3af40853	news_expansion	adzuna	0.22	0.22	{"trigger": "geographic_expansion", "locations": ["Westbrook, Middlesex County"]}	f	f	2026-08-26 04:56:43.422461	0	\N
abaa9768-2b47-477d-a9e2-c67216f29c02	45eb8c14-b33e-4710-8e6f-c0659dbecc25	job_posting	adzuna	0.43	0.43	{"roles": ["b2b technology sales rep - uncapped commission  residual income"], "job_count": 1, "locations": ["Tempe, Maricopa County"], "max_salary": 128049.34, "min_salary": 128049.34}	f	f	2026-08-26 04:56:43.42264	0	\N
7be34c07-611a-458c-9220-bc2349e05614	45eb8c14-b33e-4710-8e6f-c0659dbecc25	news_expansion	adzuna	0.22	0.22	{"trigger": "geographic_expansion", "locations": ["Tempe, Maricopa County"]}	f	f	2026-08-26 04:56:43.422661	0	\N
5672180b-1f55-4535-a783-3894717b2191	5400a977-f9f0-43c4-9ca2-46317d7b8a25	news_expansion	adzuna	0.22	0.22	{"trigger": "geographic_expansion", "locations": ["New York City, New York"]}	f	f	2026-08-26 04:56:43.422673	0	\N
5c76d1b1-4874-4954-8cd3-355a08f8497c	fc4739b3-19b0-4c3e-98e4-d0043b1f4fbc	news_expansion	adzuna	0.22	0.22	{"trigger": "geographic_expansion", "locations": ["California, US", "Campbell, Santa Clara County", "Meadows, Hudson County", "San Jose, Santa Clara County"]}	f	f	2026-08-26 04:56:43.422683	0	\N
9dc5e313-cb3a-461e-94de-626cd312ad94	cbeb6112-d896-428b-8aa2-c8e7da2974b7	news_expansion	adzuna	0.22	0.22	{"trigger": "geographic_expansion", "locations": ["Austin, Travis County", "New York City, New York", "Ohio, US", "Raleigh, Wake County", "Tempe, Maricopa County", "US"]}	f	f	2026-08-26 04:56:43.422692	0	\N
d5ff6752-bd1a-427e-b3ad-7144d6755202	b7d138b9-3dd0-40ea-b1c1-7788aafdefd0	news_expansion	adzuna	0.22	0.22	{"trigger": "geographic_expansion", "locations": ["Bronx, New York City"]}	f	f	2026-08-26 04:56:43.422702	0	\N
b5e310d2-bd7c-4a86-b7f3-0af0ca00f3d9	5c44dac1-1446-45f4-8af1-023b34905328	news_expansion	adzuna	0.22	0.22	{"trigger": "geographic_expansion", "locations": ["Chillicothe, Ross County", "New York, US"]}	f	f	2026-08-26 04:56:43.422711	0	\N
bb490a00-7e1c-4a09-84a7-169a3806a093	796ed0ed-f1a1-467e-b9d1-18cd032b91c1	news_expansion	adzuna	0.22	0.22	{"trigger": "geographic_expansion", "locations": ["Atlanta, Fulton County", "Denver, Colorado", "Scottsboro, Jackson County"]}	f	f	2026-08-26 04:56:43.422721	0	\N
\.


--
-- Data for Name: user_inputs; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.user_inputs (id, our_company_name, our_services, target_location, target_industries, target_company_size, target_keywords, target_job_titles) FROM stdin;
2	4CE CloudLabs	CRM Integration	United States	\N	50-200	\N	Salesforce Administrator
9	4CE CloudLabs	Salesforce Consulting	United States	\N	50-200	\N	Salesforce Administrator
10	4CE CloudLabs	AI Agent Development	United States	\N	50-200	\N	CTO, CIO
12	4CE CloudLabs	CRM and Enterprise RAG migration	United States	\N	50-200	\N	CIO, VP of Sales Ops, CRO
\.


--
-- Data for Name: workflow_runs; Type: TABLE DATA; Schema: public; Owner: gtm
--

COPY public.workflow_runs (id, workflow_name, status, started_at, completed_at, input_payload, output_payload, error_message, current_agent, created_at) FROM stdin;
e49ec4cd-09f2-47f5-b80d-3d0c782f76b0	manual_a1	completed	2026-08-25 12:10:33.338214	2026-08-25 12:10:56.253374	{}	{"agent": "A1", "reason": "apollo_people_search_empty", "contacts": [], "provider": "apollo", "_agent_id": "A1", "raw_count": 0, "contact_ids": [], "saved_count": 0, "scored_count": 0, "provider_page": 1, "updated_count": 0, "qualified_count": 0, "_workflow_run_id": "e49ec4cd-09f2-47f5-b80d-3d0c782f76b0", "discovery_method": "people_search_bulk_match", "inserted_contact_ids": []}	\N	\N	2026-08-25 12:10:25.24051
75ea627e-20d1-4a7f-acf2-b20aeea2e36f	manual_a1	queued	\N	\N	{}	\N	\N	\N	2026-08-25 12:21:44.545129
6a4fc190-b436-46f4-8897-0e7f4f9ddab6	manual_a1	completed	2026-08-25 16:54:01.779053	2026-08-25 16:54:15.306901	{}	{"agent": "A1", "reason": "apollo_contacts_persisted", "contacts": ["froy@balsambrands.com", "nichole.sprutte@skbcases.com", "jkbrandt@jacksonkelly.com", "bill.wallace@interceptpharma.com", "vdakshin@meso-scale.com"], "provider": "apollo", "_agent_id": "A1", "raw_count": 18, "contact_ids": ["e1a49d9d-71c7-4f4c-a39e-ecaf53abdfd5", "5d7d64f3-82ab-4226-9a86-50735600558c", "ac3fa0a5-f9cc-47da-9254-2671f62b730b", "374dde64-737e-44e1-adfa-e8543dd612e5", "9e92a2dc-b991-4a37-aa5c-dea61a203acd", "6c1959dd-efed-43fa-b57d-3b934c626568", "c395980f-6808-4076-916b-6b9bad90f22d", "6130fba6-f73a-4eba-b518-90f4e92cded5", "11e15b36-16c1-47aa-ac39-b801d53188a2", "855a05b3-2411-4944-94b4-07b7a267dab0", "db1ce271-0143-4427-8cd4-4526fd9ff07b", "501fe7c5-adae-4aa7-8db2-68b4b510dc07", "988ca8df-0a66-4fba-b983-6e0eeac2fc4d", "c6cf1cbf-f9ef-4514-a7e5-889da759b3f8", "89c38ffc-1c5b-4a3e-ab29-aa5acc42c7f3", "64a580f7-d592-439b-80bf-150d4f6820f7", "d04c09bc-0011-4c51-8ea2-1c9ffa9b4aa3", "2587ef84-0f89-4a36-8b60-d55596fd0415"], "saved_count": 18, "scored_count": 18, "provider_page": 10, "updated_count": 0, "qualified_count": 18, "_workflow_run_id": "6a4fc190-b436-46f4-8897-0e7f4f9ddab6", "discovery_method": "people_search_bulk_match", "inserted_contact_ids": ["e1a49d9d-71c7-4f4c-a39e-ecaf53abdfd5", "5d7d64f3-82ab-4226-9a86-50735600558c", "ac3fa0a5-f9cc-47da-9254-2671f62b730b", "374dde64-737e-44e1-adfa-e8543dd612e5", "9e92a2dc-b991-4a37-aa5c-dea61a203acd", "6c1959dd-efed-43fa-b57d-3b934c626568", "c395980f-6808-4076-916b-6b9bad90f22d", "6130fba6-f73a-4eba-b518-90f4e92cded5", "11e15b36-16c1-47aa-ac39-b801d53188a2", "855a05b3-2411-4944-94b4-07b7a267dab0", "db1ce271-0143-4427-8cd4-4526fd9ff07b", "501fe7c5-adae-4aa7-8db2-68b4b510dc07", "988ca8df-0a66-4fba-b983-6e0eeac2fc4d", "c6cf1cbf-f9ef-4514-a7e5-889da759b3f8", "89c38ffc-1c5b-4a3e-ab29-aa5acc42c7f3", "64a580f7-d592-439b-80bf-150d4f6820f7", "d04c09bc-0011-4c51-8ea2-1c9ffa9b4aa3", "2587ef84-0f89-4a36-8b60-d55596fd0415"]}	\N	\N	2026-08-25 16:53:58.61228
\.


--
-- Name: user_inputs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: gtm
--

SELECT pg_catalog.setval('public.user_inputs_id_seq', 15, true);


--
-- Name: agent_executions agent_executions_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.agent_executions
    ADD CONSTRAINT agent_executions_pkey PRIMARY KEY (id);


--
-- Name: agent_schedules agent_schedules_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.agent_schedules
    ADD CONSTRAINT agent_schedules_pkey PRIMARY KEY (agent_id);


--
-- Name: alembic_version alembic_version_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkey PRIMARY KEY (version_num);


--
-- Name: brand_assets brand_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.brand_assets
    ADD CONSTRAINT brand_assets_pkey PRIMARY KEY (id);


--
-- Name: contacts contacts_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.contacts
    ADD CONSTRAINT contacts_pkey PRIMARY KEY (id);


--
-- Name: conversation_threads conversation_threads_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.conversation_threads
    ADD CONSTRAINT conversation_threads_pkey PRIMARY KEY (id);


--
-- Name: deal_stage_history deal_stage_history_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.deal_stage_history
    ADD CONSTRAINT deal_stage_history_pkey PRIMARY KEY (id);


--
-- Name: deals deals_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.deals
    ADD CONSTRAINT deals_pkey PRIMARY KEY (id);


--
-- Name: funnel_events funnel_events_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.funnel_events
    ADD CONSTRAINT funnel_events_pkey PRIMARY KEY (id);


--
-- Name: generated_content generated_content_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.generated_content
    ADD CONSTRAINT generated_content_pkey PRIMARY KEY (id);


--
-- Name: outreach_drafts outreach_drafts_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.outreach_drafts
    ADD CONSTRAINT outreach_drafts_pkey PRIMARY KEY (id);


--
-- Name: outreach_log outreach_log_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.outreach_log
    ADD CONSTRAINT outreach_log_pkey PRIMARY KEY (id);


--
-- Name: pending_actions pending_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.pending_actions
    ADD CONSTRAINT pending_actions_pkey PRIMARY KEY (id);


--
-- Name: prompt_variants prompt_variants_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.prompt_variants
    ADD CONSTRAINT prompt_variants_pkey PRIMARY KEY (id);


--
-- Name: revenue_forecasts revenue_forecasts_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.revenue_forecasts
    ADD CONSTRAINT revenue_forecasts_pkey PRIMARY KEY (id);


--
-- Name: signal_conversion_registry signal_conversion_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.signal_conversion_registry
    ADD CONSTRAINT signal_conversion_registry_pkey PRIMARY KEY (id);


--
-- Name: signal_conversion_registry signal_conversion_registry_signal_type_key; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.signal_conversion_registry
    ADD CONSTRAINT signal_conversion_registry_signal_type_key UNIQUE (signal_type);


--
-- Name: signal_events signal_events_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.signal_events
    ADD CONSTRAINT signal_events_pkey PRIMARY KEY (id);


--
-- Name: outreach_log uq_outreach_contact_campaign; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.outreach_log
    ADD CONSTRAINT uq_outreach_contact_campaign UNIQUE (contact_id, campaign_type);


--
-- Name: user_inputs user_inputs_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.user_inputs
    ADD CONSTRAINT user_inputs_pkey PRIMARY KEY (id);


--
-- Name: workflow_runs workflow_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.workflow_runs
    ADD CONSTRAINT workflow_runs_pkey PRIMARY KEY (id);


--
-- Name: ix_agent_executions_agent_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_agent_executions_agent_id ON public.agent_executions USING btree (agent_id);


--
-- Name: ix_agent_executions_status; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_agent_executions_status ON public.agent_executions USING btree (status);


--
-- Name: ix_agent_executions_task_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_agent_executions_task_id ON public.agent_executions USING btree (task_id);


--
-- Name: ix_agent_executions_workflow_agent; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_agent_executions_workflow_agent ON public.agent_executions USING btree (workflow_run_id, agent_id);


--
-- Name: ix_agent_executions_workflow_run_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_agent_executions_workflow_run_id ON public.agent_executions USING btree (workflow_run_id);


--
-- Name: ix_agent_schedules_enabled; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_agent_schedules_enabled ON public.agent_schedules USING btree (enabled);


--
-- Name: ix_contacts_company; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_contacts_company ON public.contacts USING btree (company);


--
-- Name: ix_contacts_company_domain; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_contacts_company_domain ON public.contacts USING btree (company_domain);


--
-- Name: ix_contacts_do_not_contact; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_contacts_do_not_contact ON public.contacts USING btree (do_not_contact);


--
-- Name: ix_contacts_email; Type: INDEX; Schema: public; Owner: gtm
--

CREATE UNIQUE INDEX ix_contacts_email ON public.contacts USING btree (email);


--
-- Name: ix_contacts_icp_score; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_contacts_icp_score ON public.contacts USING btree (icp_score);


--
-- Name: ix_contacts_icp_score_dnc; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_contacts_icp_score_dnc ON public.contacts USING btree (icp_score, do_not_contact);


--
-- Name: ix_contacts_user_input_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_contacts_user_input_id ON public.contacts USING btree (user_input_id);


--
-- Name: ix_conversation_threads_contact_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_conversation_threads_contact_id ON public.conversation_threads USING btree (contact_id);


--
-- Name: ix_conversation_threads_contact_time; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_conversation_threads_contact_time ON public.conversation_threads USING btree (contact_id, occurred_at);


--
-- Name: ix_conversation_threads_occurred_at; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_conversation_threads_occurred_at ON public.conversation_threads USING btree (occurred_at);


--
-- Name: ix_deal_stage_history_deal_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_deal_stage_history_deal_id ON public.deal_stage_history USING btree (deal_id);


--
-- Name: ix_deals_contact_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_deals_contact_id ON public.deals USING btree (contact_id);


--
-- Name: ix_deals_hubspot_deal_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE UNIQUE INDEX ix_deals_hubspot_deal_id ON public.deals USING btree (hubspot_deal_id);


--
-- Name: ix_deals_stage; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_deals_stage ON public.deals USING btree (stage);


--
-- Name: ix_funnel_events_contact_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_funnel_events_contact_id ON public.funnel_events USING btree (contact_id);


--
-- Name: ix_funnel_events_deal_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_funnel_events_deal_id ON public.funnel_events USING btree (deal_id);


--
-- Name: ix_funnel_events_event_type; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_funnel_events_event_type ON public.funnel_events USING btree (event_type);


--
-- Name: ix_funnel_events_timestamp; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_funnel_events_timestamp ON public.funnel_events USING btree ("timestamp");


--
-- Name: ix_funnel_events_type_time; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_funnel_events_type_time ON public.funnel_events USING btree (event_type, "timestamp");


--
-- Name: ix_outreach_drafts_contact_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_outreach_drafts_contact_id ON public.outreach_drafts USING btree (contact_id);


--
-- Name: ix_outreach_log_contact_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_outreach_log_contact_id ON public.outreach_log USING btree (contact_id);


--
-- Name: ix_outreach_log_sent_at; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_outreach_log_sent_at ON public.outreach_log USING btree (sent_at);


--
-- Name: ix_pending_actions_status; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_pending_actions_status ON public.pending_actions USING btree (status);


--
-- Name: ix_pending_actions_status_created; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_pending_actions_status_created ON public.pending_actions USING btree (status, created_at);


--
-- Name: ix_prompt_variants_signal_type; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_prompt_variants_signal_type ON public.prompt_variants USING btree (signal_type);


--
-- Name: ix_revenue_forecasts_calculated_at; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_revenue_forecasts_calculated_at ON public.revenue_forecasts USING btree (calculated_at);


--
-- Name: ix_signal_events_contact_id; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_signal_events_contact_id ON public.signal_events USING btree (contact_id);


--
-- Name: ix_signal_events_contact_type; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_signal_events_contact_type ON public.signal_events USING btree (contact_id, signal_type);


--
-- Name: ix_signal_events_signal_type; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_signal_events_signal_type ON public.signal_events USING btree (signal_type);


--
-- Name: ix_workflow_runs_status; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_workflow_runs_status ON public.workflow_runs USING btree (status);


--
-- Name: ix_workflow_runs_workflow_name; Type: INDEX; Schema: public; Owner: gtm
--

CREATE INDEX ix_workflow_runs_workflow_name ON public.workflow_runs USING btree (workflow_name);


--
-- Name: agent_executions agent_executions_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.agent_executions
    ADD CONSTRAINT agent_executions_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id);


--
-- Name: contacts contacts_user_input_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.contacts
    ADD CONSTRAINT contacts_user_input_id_fkey FOREIGN KEY (user_input_id) REFERENCES public.user_inputs(id) ON DELETE SET NULL;


--
-- Name: conversation_threads conversation_threads_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.conversation_threads
    ADD CONSTRAINT conversation_threads_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.contacts(id);


--
-- Name: conversation_threads conversation_threads_outreach_log_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.conversation_threads
    ADD CONSTRAINT conversation_threads_outreach_log_id_fkey FOREIGN KEY (outreach_log_id) REFERENCES public.outreach_log(id);


--
-- Name: deal_stage_history deal_stage_history_deal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.deal_stage_history
    ADD CONSTRAINT deal_stage_history_deal_id_fkey FOREIGN KEY (deal_id) REFERENCES public.deals(id);


--
-- Name: deals deals_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.deals
    ADD CONSTRAINT deals_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.contacts(id);


--
-- Name: funnel_events funnel_events_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.funnel_events
    ADD CONSTRAINT funnel_events_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.contacts(id);


--
-- Name: funnel_events funnel_events_deal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.funnel_events
    ADD CONSTRAINT funnel_events_deal_id_fkey FOREIGN KEY (deal_id) REFERENCES public.deals(id);


--
-- Name: outreach_drafts outreach_drafts_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.outreach_drafts
    ADD CONSTRAINT outreach_drafts_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.contacts(id);


--
-- Name: outreach_drafts outreach_drafts_signal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.outreach_drafts
    ADD CONSTRAINT outreach_drafts_signal_id_fkey FOREIGN KEY (signal_id) REFERENCES public.signal_events(id);


--
-- Name: outreach_log outreach_log_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.outreach_log
    ADD CONSTRAINT outreach_log_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.contacts(id);


--
-- Name: outreach_log outreach_log_signal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.outreach_log
    ADD CONSTRAINT outreach_log_signal_id_fkey FOREIGN KEY (signal_id) REFERENCES public.signal_events(id);


--
-- Name: signal_events signal_events_contact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: gtm
--

ALTER TABLE ONLY public.signal_events
    ADD CONSTRAINT signal_events_contact_id_fkey FOREIGN KEY (contact_id) REFERENCES public.contacts(id);


--
-- PostgreSQL database dump complete
--

\unrestrict 7idPnNyxemFpL6d7BEN0eAQbSJoX1h4G16pJpkzuDdbOp8AWzV99uT4xhHhx0dk

