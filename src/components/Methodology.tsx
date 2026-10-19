import type { ReactNode } from "react";

import type { SiteLanguage } from "./SiteHeader.tsx";

type MethodologyCard = {
  eyebrow: string;
  title: string;
  paragraphs: readonly ReactNode[];
};

type MethodologyCopy = {
  headingEyebrow: string;
  headingTitle: string;
  headingBody: string;
  tocLabel: string;
  tocAriaLabel: string;
  toc: ReadonlyArray<{ href: string; label: string }>;
  pipelineId: string;
  pipelineEyebrow: string;
  pipelineTitle: string;
  pipelineBody: string;
  pipelineAriaLabel: string;
  steps: ReadonlyArray<{ number: string; title: string; body: string }>;
  collectionId: string;
  collectionEyebrow: string;
  collectionTitle: string;
  collectionBody: string;
  collectionCards: readonly MethodologyCard[];
  matchingId: string;
  matchingEyebrow: string;
  matchingTitle: string;
  matchingBody: string;
  matchingRules: readonly string[];
  scoreTitle: string;
  scoreBody: string;
  publicationId: string;
  publicationEyebrow: string;
  publicationTitle: string;
  publicationBody: string;
  publicFields: ReadonlyArray<readonly [string, string]>;
  mergeTitle: string;
  mergeBody: string;
  publicationReport: ReactNode;
  historyId: string;
  historyEyebrow: string;
  historyTitle: string;
  historyBody: string;
  historyCards: readonly MethodologyCard[];
  limitationsId: string;
  limitationsEyebrow: string;
  limitationsTitle: string;
  limitationsBody: string;
  limitationCards: readonly MethodologyCard[];
  correctionReport: ReactNode;
};

const englishCopy: MethodologyCopy = {
  headingEyebrow: "Methodology",
  headingTitle: "How a signal reaches Radar",
  headingBody:
    "HECAVEX Radar is a passive, explainable screening pipeline for possible phishing and impersonation relevant to Lithuania. It favors precision over volume and never treats one automated signal as proof of malicious intent.",
  tocLabel: "On this page",
  tocAriaLabel: "Methodology sections",
  toc: [
    { href: "#pipeline", label: "Pipeline" },
    { href: "#collection", label: "Collection" },
    { href: "#matching", label: "Brand matching" },
    { href: "#publication", label: "Publication" },
    { href: "#history", label: "History" },
    { href: "#limitations", label: "Limits and safety" },
  ],
  pipelineId: "pipeline",
  pipelineEyebrow: "Pipeline",
  pipelineTitle: "Four bounded stages",
  pipelineBody: "Every published row follows the same normalization, brand-scoping, safety, and merge path.",
  pipelineAriaLabel: "Publication stages",
  steps: [
    {
      number: "01",
      title: "Observe",
      body: "Read passive public observations from Certificate Transparency, existing public URLScan reports, and deliberately sanitized HECAVEX inputs.",
    },
    {
      number: "02",
      title: "Match",
      body: "Compare hostnames with a reviewed Lithuanian-brand registry while suppressing official domains and known lexical collisions.",
    },
    {
      number: "03",
      title: "Validate",
      body: "Require one unambiguous brand, current evidence, safe fields, and the relevant match-score threshold before publication.",
    },
    {
      number: "04",
      title: "Publish",
      body: "Defang dashboard indicators, mark public observations as suspected, merge duplicate hosts, and project normalized domain observations into the static STIX 2.1 feed.",
    },
  ],
  collectionId: "collection",
  collectionEyebrow: "Collection",
  collectionTitle: "Passive observations only",
  collectionBody: "Radar does not browse a candidate host, submit it for scanning, or turn a defanged indicator into a live link.",
  collectionCards: [
    {
      eyebrow: "Certificate Transparency",
      title: "CertStream",
      paragraphs: [
        "Scheduled collection listens to live certificate events for eight minutes per run, normally four times per hour. Each DNS name is scored independently and qualifying matches are stored in Europe/Vilnius daily archives.",
        "That schedule provides at most 768 listening minutes per day, or 53.3% of wall-clock time. It is live sampling, not a daily certificate dump: events outside successful listening windows are not replayed or backfilled by the current collector. Actions can start late, drop a schedule, or fail, so actual observation can be lower.",
      ],
    },
    {
      eyebrow: "Checkpointed CT search",
      title: "Bounded keyword replay",
      paragraphs: [
        "An hourly crt.sh search rotates across reviewed brand terms and persists one numeric cursor per query. It bootstraps only a bounded recent window, rechecks a limited overlap for late indexing, resumes an explicit backlog before rotation, re-applies the same matcher, and retains discovery lineage in the CT archive.",
        "This can recover indexed results missed by a live sample, but it is not an enumeration of every CT log. Provider availability, indexing, result limits, and the deliberately bounded query set remain coverage limits.",
      ],
    },
    {
      eyebrow: "Existing public reports",
      title: "URLScan",
      paragraphs: [
        "Radar searches already-existing public results using exact candidate domains, reviewed brand terms, page titles, and tightly bounded primary-HTML SHA-256 pivots. It never submits a new scan.",
        "Search summaries and result details must both report public visibility. URLScan can enrich CertStream with screenshots, hashes, and hosting metadata, but it is not required for a qualifying CertStream row.",
      ],
    },
    {
      eyebrow: "Deliberately sanitized input",
      title: "HECAVEX",
      paragraphs: [
        "A deployment may configure a bounded HTTPS JSON export. Supplied source labels are ignored; accepted rows are attributed to HECAVEX and must pass the same brand, URL, timestamp, and evidence validation.",
        <>
          An operator can also deliberately export one sanitized local review candidate. The public
          <code> discoveredVia</code> value distinguishes that path from the service export. Internal collectors,
          proprietary detection logic, analyst notes, credentials, and private historical data remain outside this project.
        </>,
      ],
    },
    {
      eyebrow: "Published-candidate context",
      title: "DNS and RDAP",
      paragraphs: [
        "Four times daily, Radar rotates through already-published candidates using DNS-over-HTTPS and the IANA RDAP bootstrap. RDAP is requested for the registrable parent and that defanged scope remains visible. It never requests the candidate webpage or executes its content.",
        "Sidecars may expose defanged DNS answers, minimum TTL, registrar, lifecycle dates, and statuses. Registrant identities are excluded, records expire after a bounded retention window, and shared infrastructure is association, not attribution.",
      ],
    },
  ],
  matchingId: "matching",
  matchingEyebrow: "Brand matching",
  matchingTitle: "Conservative by construction",
  matchingBody:
    "The public registry records reviewed aliases, fuzzy aliases, official domains, exclusions, and collision terms for brands relevant to Lithuania. Registry entries cannot supply executable regular expressions.",
  matchingRules: [
    "Normalize the hostname, then reject malformed input, reviewed official domains, excluded domains, and their subdomains.",
    "Match an alias as a complete hyphen-delimited token or complete token sequence within one DNS label. Suspicious context must normally occur in that same label; for aliases longer than four characters, a suspicious word in another label of the same hostname also counts, except where the alias is the whole registrable name under a ccTLD or a common generic TLD.",
    "Suspicious words include reviewed Lithuanian and multinational delivery and payment lure vocabulary, Baltic market markers such as -lt, compounds that start with a reviewed word, and words sharing a long stem with one.",
    "Allow narrowly joined forms such as a reviewed suspicious prefix or suffix attached directly to a sufficiently long brand alias.",
    "Apply opt-in restricted Damerau–Levenshtein matching only to reviewed single-word fuzzy aliases (every single-word alias of seven or more characters), with the same suspicious-context requirement.",
    "Apply the separate reviewed IDN visual profile only within a matched alias in one label. Its curated substitutions supplement Radar's existing comparison derived from UTS #39 data; generic Punycode or unrelated Unicode decoration is insufficient.",
    "Reject excluded terms, multi-brand evidence, and any declared brand that conflicts with the current hostname match.",
  ],
  scoreTitle: "Scoring threshold",
  scoreBody:
    "Different top-level domains, multiple hyphens, suspicious words, and punycode can increase a score only after valid brand evidence exists. The default CertStream and URLScan domain threshold is 80/100.",
  publicationId: "publication",
  publicationEyebrow: "Publication",
  publicationTitle: "What the dashboard exposes",
  publicationBody:
    "The publisher projects durable observations under the current registry and review policy into a complete hostname inventory and period metrics. The bounded current shortlist, snapshot v2 and observation-only STIX projection remain separate compatibility views.",
  publicFields: [
    ["Indicator", "A normalized, defanged domain or URL. Credentials, query strings, fragments, and unsafe path data are removed."],
    ["Timeline", "First-seen and last-seen timestamps from accepted observations, normalized to UTC."],
    ["Source", "CertStream, URLScan, or HECAVEX. Controlled discovery lineage distinguishes configured service exports from explicit sanitized review candidates."],
    ["Status", "CertStream and URLScan rows remain suspected. Active, offline, or mitigated lifecycle states require a configured HECAVEX observation."],
    ["Target", "Exactly one brand resolved through the current reviewed registry and collision checks."],
    ["Evidence", "Separate name-only, corroborated, and analyst-reviewed tiers, with controlled discovery and corroboration lineage."],
    ["Context", "Optional public URLScan evidence plus bounded point-in-time DNS and RDAP registration context. Missing context remains unknown."],
    ["Match score", "An integer rule score from 0 to 100. It ranks matcher strength; it is not probability, analyst confidence, or a verdict."],
  ],
  mergeTitle: "Merge behavior",
  mergeBody:
    "One row represents one observed host. Merging keeps the earliest first-seen value, latest last-seen value, union of sources and hashes, most specific safe path, and highest match score. Conflicting non-null brands invalidate the merged row.",
  publicationReport: (
    <>
      The static <a href="/data/radar.stix.json">STIX 2.1 pull feed</a> contains raw domain-name observables for
      potential or suspected candidates. The separate <a href="/data/radar-reviewed.stix.json">reviewed feed</a> can
      contain only explicit, expiring analyst confirmations. Neither feed is a TAXII endpoint, automatic blocklist,
      maliciousness verdict for unreviewed rows, or attribution claim.
    </>
  ),
  historyId: "history",
  historyEyebrow: "History and review",
  historyTitle: "Append observations; infer nothing from absence",
  historyBody:
    "Durable observation identity combines the canonical hostname, sorted sources and effective observation time. Replays preserve the original provider time or declared collector fallback and merge annotations without increasing observation counts. Legacy event IDs are provenance, not independent observation identities.",
  historyCards: [
    {
      eyebrow: "Primary period totals", title: "One hostname per selected period",
      paragraphs: [<>The <a href="/data/observed-hostnames-v1.json">complete hostname index</a> and digest-bound <a href="/data/period-metrics-v1.json">period metrics</a> count unique canonical hostnames; subdomains count separately and private-PSL groups are secondary. 30/90/365-day and calendar views use recorded observation times with their declared provenance. Missing days are not filled between first and last seen. All recorded means the available retained history, not a complete lifetime census.</>],
    },
    {
      eyebrow: "Separate clocks", title: "Observed, recorded and published",
      paragraphs: ["First/last seen use provider observation time or declared collector fallback when a usable provider timestamp is unavailable. Historical timing provenance remains incomplete: older normalized times cannot be assumed to be provider times. Per-hostname time origins summarize all recorded observations, not each first/last timestamp. Radar recording and captured verified publication receipts use separate clocks. Receipts cover newly tracked hostnames with known recording times only; legacy hostnames with unknown first-recorded time retain a null first-publication clock. The first captured receipt since activation does not establish the earliest-ever public date. Unknown historical clocks remain null; a sync, import or legacy first-publication marker cannot substitute for them. Recording and publication totals query their own clocks independently of observation-period membership."],
    },
    {
      eyebrow: "Legacy compatibility trail",
      title: "Thirty-day event window",
      paragraphs: ["Legacy daily, defanged NDJSON events compact after the configured detail window into a bounded signal summary, retained for two years by default. This compatibility expiry does not expire durable observation facts or define the primary period inventory."],
    },
    {
      eyebrow: "Status provenance",
      title: "Only explicit transitions",
      paragraphs: ["CertStream and URLScan remain suspected. A transition to active, offline, or mitigated is recorded only when a supported HECAVEX observation supplies it. Falling outside a lookback window creates no transition."],
    },
    {
      eyebrow: "Corrections",
      title: "Private notes stay private",
      paragraphs: ["HECAVEX operator review uses an append-only database outside Git. Only explicitly exported, defanged suppressions and candidates reach the public pipeline; analyst notes and identities are never included."],
    },
  ],
  limitationsId: "limitations",
  limitationsEyebrow: "Limits and safety",
  limitationsTitle: "Read the signals as leads",
  limitationsBody: "Coverage gaps and missing enrichment are expected. Neither a listing nor an absence from Radar is a verdict.",
  limitationCards: [
    { eyebrow: "Interpretation", title: "A lead, not attribution", paragraphs: ["A row indicates possible phishing or impersonation. It does not prove malicious intent, current liveness, ownership, attribution, compromise, or that a person has interacted with the domain."] },
    { eyebrow: "IDN display", title: "Each application makes its own choice", paragraphs: [<>The <a href="https://haveibeensquatted.com/blog/turning-idn-edge-cases-into-typosquats">3 October 2026 IDN research</a> demonstrated separate browser-display, navigation, registry and email-client decisions. Those dated results do not predict a current application&apos;s behavior. Unicode display, valid TLS and no warning do not establish safety.</>] },
    { eyebrow: "Coverage", title: "Intentionally incomplete", paragraphs: ["Live CertStream is sampled, the checkpointed CT search is provider-indexed and bounded, URLScan exposes only existing public reports, and context is optional. Missing evidence does not make a candidate safe or prevent an independently qualifying CT candidate from appearing."] },
    { eyebrow: "Redirects and cloaking", title: "A redirect is behavior, not clearance", paragraphs: ["A submitted candidate remains the indicator when a public URLScan report redirects elsewhere. Radar records the defanged destination as context, but does not assign that destination's host data or screenshot to the candidate. Different visitors can receive different content or redirects."] },
    { eyebrow: "Browsing safety", title: "Indicators stay defanged", paragraphs: ["The dashboard never links to observed hosts. Evidence controls can contact exactly urlscan.io after a user chooses to open them; report and screenshot URLs are validated before publication."] },
    { eyebrow: "Corrections", title: "Rules are re-applied", paragraphs: ["Archived observations are checked against the current registry during synchronization, so corrected brand mappings and official-domain additions remove stale false positives from later snapshots."] },
    { eyebrow: "Service boundary", title: "Best effort, no SLA", paragraphs: ["HECAVEX operates Radar as best-effort public research. It is not continuous brand monitoring, victim notification, incident response, takedown, or an availability or response commitment."] },
    { eyebrow: "Operational evidence", title: "Snapshot state has limits", paragraphs: ["Source timestamps show archive reads performed by the publisher. The separate public collection-health document reports actual timing, aggregate counts, late starts, outcome, last success, and freshness for only the latest CertStream attempt. Rolling pipeline health also reports sanitized CT-search and DNS/RDAP run summaries; none of these artifacts proves complete global coverage."] },
  ],
  correctionReport: <><span>Believe a listing is incorrect? </span><a href="mailto:info@hecavex.com?subject=HECAVEX%20Radar%20false%20positive">Report a false positive</a> or <a href="https://github.com/Hecavex/radar.hecavex.com/issues/new?template=false-positive.yml">open a public GitHub issue</a>.</>,
};

const lithuanianCopy: MethodologyCopy = {
  headingEyebrow: "Metodologija",
  headingTitle: "Kaip signalas patenka į Radarą",
  headingBody:
    "HECAVEX Radaras yra pasyvi ir paaiškinama Lietuvai aktualių galimų phishing bei apsimetimo atvejų atrankos sistema. Pirmenybė teikiama tikslumui, o ne kiekiui, ir vienas automatinis signalas niekada nelaikomas kenkėjiško ketinimo įrodymu.",
  tocLabel: "Šiame puslapyje",
  tocAriaLabel: "Metodologijos skyriai",
  toc: [
    { href: "#procesas", label: "Procesas" },
    { href: "#rinkimas", label: "Duomenų rinkimas" },
    { href: "#atitikimas", label: "Prekių ženklų atitiktis" },
    { href: "#skelbimas", label: "Skelbimas" },
    { href: "#istorija", label: "Istorija" },
    { href: "#ribos", label: "Ribos ir saugumas" },
  ],
  pipelineId: "procesas",
  pipelineEyebrow: "Procesas",
  pipelineTitle: "Keturi aiškiai apriboti etapai",
  pipelineBody: "Kiekviena paskelbta eilutė pereina tą patį normalizavimo, prekių ženklo apimties nustatymo, saugos ir sujungimo procesą.",
  pipelineAriaLabel: "Skelbimo etapai",
  steps: [
    { number: "01", title: "Stebėti", body: "Skaityti pasyvius viešus Certificate Transparency stebėjimus, jau esamas viešas URLScan ataskaitas ir sąmoningai neutralizuotas HECAVEX įvestis." },
    { number: "02", title: "Palyginti", body: "Palyginti pagrindinių kompiuterių vardus su peržiūrėtu Lietuvai aktualių prekių ženklų registru, atmetant oficialius domenus ir žinomas leksines kolizijas." },
    { number: "03", title: "Patikrinti", body: "Prieš skelbiant reikalauti vieno nedviprasmiško prekių ženklo, aktualių įrodymų, saugių laukų ir tinkamos atitikties balo ribos." },
    { number: "04", title: "Paskelbti", body: "Suvestinėje neutralizuoti indikatorius, viešus stebėjimus pažymėti kaip įtariamus, sujungti pasikartojančius pagrindinių kompiuterių vardus ir normalizuotus domenų stebėjimus pateikti statiniame STIX 2.1 kanale." },
  ],
  collectionId: "rinkimas",
  collectionEyebrow: "Duomenų rinkimas",
  collectionTitle: "Tik pasyvūs stebėjimai",
  collectionBody: "Radaras neatveria kandidato svetainės, nepateikia jos skenavimui ir nepaverčia neutralizuoto indikatoriaus aktyvia nuoroda.",
  collectionCards: [
    {
      eyebrow: "Certificate Transparency",
      title: "CertStream",
      paragraphs: [
        "Suplanuotas rinktuvas gyvų sertifikatų įvykių klausosi po aštuonias minutes per paleidimą, įprastai keturis kartus per valandą. Kiekvienas DNS vardas vertinamas atskirai, o reikalavimus atitinkantys rezultatai saugomi kasdieniuose Europe/Vilnius archyvuose.",
        "Toks grafikas suteikia daugiausia 768 klausymosi minutes per parą, arba 53,3 proc. paros laiko. Tai gyvo srauto atranka, o ne kasdienė sertifikatų kopija: įvykiai už sėkmingų klausymosi langų nėra pakartojami ar atkuriami dabartinio rinktuvo. Veiksmai gali prasidėti vėliau, praleisti suplanuotą paleidimą ar nepavykti, todėl tikroji aprėptis gali būti mažesnė.",
      ],
    },
    {
      eyebrow: "Kontroliniais taškais paremta CT paieška",
      title: "Ribotas raktažodžių atkūrimas",
      paragraphs: [
        "Kas valandą vykdoma crt.sh paieška rotuoja per peržiūrėtus prekių ženklų terminus ir kiekvienai užklausai išsaugo skaitinį žymeklį. Ji pradeda nuo riboto naujausio laikotarpio, pakartotinai tikrina nedidelę persidengiančią dalį dėl vėlyvo indeksavimo, prieš rotuodama tęsia aiškiai nustatytą atsilikimą, iš naujo taiko tą pačią atitikties sistemą ir CT archyve išsaugo aptikimo kilmę.",
        "Taip galima atkurti indeksuotus rezultatus, kuriuos praleido gyvo srauto atranka, tačiau tai nėra visų CT žurnalų surašymas. Paslaugos pasiekiamumas, indeksavimas, rezultatų ribos ir sąmoningai apribotas užklausų rinkinys vis tiek riboja aprėptį.",
      ],
    },
    {
      eyebrow: "Jau esamos viešos ataskaitos",
      title: "URLScan",
      paragraphs: [
        "Radaras ieško jau esamų viešų rezultatų pagal tikslius kandidatų domenus, peržiūrėtus prekių ženklų terminus, puslapių pavadinimus ir griežtai apribotus pirminio HTML SHA-256 atspaudus. Naujas skenavimas niekada nepateikiamas.",
        "Tiek paieškos suvestinė, tiek išsami rezultato informacija turi nurodyti viešą matomumą. URLScan gali papildyti CertStream ekrano kopijomis, maišos reikšmėmis ir prieglobos metaduomenimis, tačiau tinkamam CertStream įrašui URLScan duomenys nėra privalomi.",
      ],
    },
    {
      eyebrow: "Sąmoningai neutralizuota įvestis",
      title: "HECAVEX",
      paragraphs: [
        "Dieginyje galima nustatyti ribotą HTTPS JSON eksportą. Pateiktos šaltinių žymos ignoruojamos; priimti įrašai priskiriami HECAVEX ir turi pereiti tą patį prekių ženklo, URL, laiko žymos bei įrodymų tikrinimą.",
        <>Operatorius taip pat gali sąmoningai eksportuoti vieną neutralizuotą vietinės peržiūros kandidatą. Vieša<code> discoveredVia</code> reikšmė atskiria šį kelią nuo paslaugos eksporto. Vidiniai rinktuvai, nevieša aptikimo logika, analitiko pastabos, prisijungimo duomenys ir privatūs istoriniai duomenys į šį projektą nepatenka.</>,
      ],
    },
    {
      eyebrow: "Paskelbtų kandidatų kontekstas",
      title: "DNS ir RDAP",
      paragraphs: [
        "Keturis kartus per dieną Radaras rotuoja per jau paskelbtus kandidatus, naudodamas DNS per HTTPS ir IANA RDAP pradinį registrą. RDAP užklausa teikiama registruojamam pirminiam domenui, o ši neutralizuota apimtis lieka matoma. Kandidato svetainė niekada neužklausiama ir jos turinys nevykdomas.",
        "Papildomi failai gali pateikti neutralizuotus DNS atsakymus, mažiausią TTL, registratorių, gyvavimo ciklo datas ir būsenas. Registruotojų tapatybės neįtraukiamos, įrašai pašalinami pasibaigus ribotam saugojimo laikotarpiui, o bendra infrastruktūra reiškia sąsają, ne priskyrimą.",
      ],
    },
  ],
  matchingId: "atitikimas",
  matchingEyebrow: "Prekių ženklų atitiktis",
  matchingTitle: "Nuo pradžių sukurta konservatyviai",
  matchingBody: "Viešame registre saugomi peržiūrėti pavadinimai, apytikslei atitikčiai skirti pavadinimai, oficialūs domenai, išimtys ir kolizijų terminai, susiję su Lietuvai aktualiais prekių ženklais. Registro įrašai negali pateikti vykdomų reguliariųjų išraiškų.",
  matchingRules: [
    "Normalizuoti pagrindinio kompiuterio vardą, tada atmesti netaisyklingą įvestį, peržiūrėtus oficialius domenus, neįtraukiamus domenus ir jų subdomenus.",
    "Pavadinimą atitikti kaip visą brūkšneliais atskirtą elementą arba visą elementų seką vienoje DNS žymoje. Įtartinas kontekstas paprastai turi būti toje pačioje žymoje; ilgesniems nei keturių simbolių pavadinimams tinka ir įtartinas žodis kitoje to paties vardo žymoje, išskyrus atvejus, kai pavadinimas yra visas registruojamas vardas nacionaliniame ar dažname bendrajame aukščiausiojo lygio domene.",
    "Įtartini žodžiai apima peržiūrėtą lietuvišką ir tarptautinį siuntų bei mokėjimų apgaulės žodyną, Baltijos rinkos žymas, pavyzdžiui, -lt, junginius, prasidedančius peržiūrėtu žodžiu, ir žodžius, turinčius su juo bendrą ilgą šaknį.",
    "Leisti tik siaurai apibrėžtas sujungtas formas, pavyzdžiui, peržiūrėtą įtartiną priešdėlį ar priesagą, tiesiogiai prijungtą prie pakankamai ilgo prekių ženklo pavadinimo.",
    "Pasirinktinį ribotą Damerau–Levenshtein atitikimą taikyti tik peržiūrėtiems vieno žodžio apytikslės atitikties pavadinimams (visiems vieno žodžio pavadinimams iš septynių ar daugiau simbolių), reikalaujant tokio paties įtartino konteksto.",
    "Atskirą peržiūrėtą IDN vaizdinio panašumo profilį taikyti tik sutampančiame pavadinime vienoje domeno dalyje. Peržiūrėtos pakaitos papildo esamą Radar palyginimą pagal UTS #39 duomenis; vien Punycode ar nesusijusių Unicode ženklų nepakanka.",
    "Atmesti neįtraukiamus terminus, kelių prekių ženklų įrodymus ir bet kurį deklaruotą prekių ženklą, kuris prieštarauja dabartinei pagrindinio kompiuterio vardo atitikčiai.",
  ],
  scoreTitle: "Balo riba",
  scoreBody: "Skirtingi aukščiausio lygio domenai, keli brūkšneliai, įtartini žodžiai ir punycode gali didinti balą tik tada, kai jau yra galiojantis prekių ženklo įrodymas. Numatytoji CertStream ir URLScan domenų riba yra 80/100.",
  publicationId: "skelbimas",
  publicationEyebrow: "Skelbimas",
  publicationTitle: "Ką pateikia suvestinė",
  publicationBody: "Skelbėjas ilgalaikius stebėjimus pagal dabartinį registrą ir peržiūros politiką projektuoja į visą domenų vardų rinkinį bei laikotarpių rodiklius. Ribotas dabartinis trumpasis sąrašas, 2 versijos suvestinė ir tik stebėjimais pagrįsta STIX projekcija lieka atskiri suderinamumo vaizdai.",
  publicFields: [
    ["Indikatorius", "Normalizuotas ir neutralizuotas domenas arba URL. Prisijungimo duomenys, užklausų eilutės, fragmentai ir nesaugūs kelio duomenys pašalinami."],
    ["Laiko seka", "Pirmo ir paskutinio priimto stebėjimo laiko žymos, normalizuotos į UTC."],
    ["Šaltinis", "CertStream, URLScan arba HECAVEX. Kontroliuojama aptikimo kilmė atskiria nustatytus paslaugos eksportus nuo aiškiai neutralizuotų peržiūros kandidatų."],
    ["Būsena", "CertStream ir URLScan įrašai lieka įtariami. Aktyviai, nepasiekiamai ar suvaldytai gyvavimo ciklo būsenai būtinas nustatytas HECAVEX stebėjimas."],
    ["Taikinys", "Tik vienas prekių ženklas, nustatytas pagal dabartinį peržiūrėtą registrą ir kolizijų patikras."],
    ["Įrodymai", "Atskiri tik pavadinimu pagrįsti, papildomu šaltiniu patvirtinti ir analitiko peržiūrėti lygiai su kontroliuojama aptikimo bei patvirtinimo kilme."],
    ["Kontekstas", "Pasirinktiniai vieši URLScan įrodymai bei ribotas konkretaus laiko DNS ir RDAP registracijos kontekstas. Trūkstamas kontekstas lieka nežinomas."],
    ["Atitikties balas", "Sveikasis taisyklių balas nuo 0 iki 100. Jis rikiuoja atitikties stiprumą, tačiau nėra tikimybė, analitiko pasitikėjimas ar nuosprendis."],
  ],
  mergeTitle: "Sujungimo elgsena",
  mergeBody: "Viena eilutė žymi vieną stebėtą pagrindinį kompiuterį. Sujungiant išsaugomas ankstyviausias pirmo stebėjimo laikas, vėliausias paskutinio stebėjimo laikas, šaltinių ir maišos reikšmių sąjunga, tiksliausias saugus kelias bei aukščiausias atitikties balas. Nesuderinami neneuliniai prekių ženklai sujungtą eilutę padaro netinkamą.",
  publicationReport: <><span>Statiniame </span><a href="/data/radar.stix.json">STIX 2.1 atsisiuntimo kanale</a><span> pateikiami neapdoroti galimų ar įtariamų kandidatų domenų vardų stebimieji objektai. Atskirame </span><a href="/data/radar-reviewed.stix.json">peržiūrėtų signalų kanale</a><span> gali būti tik aiškūs ir galiojimo laiką turintys analitiko patvirtinimai. Nė vienas kanalas nėra TAXII galinis taškas, automatinis blokavimo sąrašas, neperžiūrėtų įrašų kenkėjiškumo nuosprendis ar priskyrimo teiginys.</span></>,
  historyId: "istorija",
  historyEyebrow: "Istorija ir peržiūra",
  historyTitle: "Stebėjimus pridėti, iš nebuvimo nieko nespręsti",
  historyBody: "Ilgalaikio stebėjimo tapatybę sudaro kanoninis domeno vardas, surikiuoti šaltiniai ir faktinis stebėjimo laikas. Pakartotinis apdorojimas išsaugo pradinį teikėjo laiką arba deklaruotą rinkiklio laiką ir sujungia anotacijas nedidindamas stebėjimų skaičiaus. Ankstesni įvykių ID yra kilmės duomenys, o ne atskiros stebėjimų tapatybės.",
  historyCards: [
    { eyebrow: "Pagrindiniai laikotarpio rodikliai", title: "Vienas domeno vardas laikotarpiu", paragraphs: [<>Viso <a href="/data/observed-hostnames-v1.json">domenų vardų rinkinio rodyklė</a> ir maiša susieti <a href="/data/period-metrics-v1.json">laikotarpių rodikliai</a> skaičiuoja unikalius kanoninius domenų vardus; subdomenai skaičiuojami atskirai, o grupės pagal privatų PSL yra antrinis rodiklis. 30, 90, 365 dienų ir kalendoriniai vaizdai naudoja išsaugotus stebėjimų laikus su deklaruota kilme. Tarp pirmo ir paskutinio stebėjimo trūkstamos dienos neužpildomos. Visa išsaugota istorija reiškia turimą rinkinį, o ne pilną visų laikų apskaitą.</>] },
    { eyebrow: "Atskiri laikai", title: "Stebėta, įrašyta ir paskelbta", paragraphs: ["Pirmas ir paskutinis stebėjimas yra teikėjo stebėjimo laikas arba deklaruotas rinkiklio laikas, kai tinkama teikėjo laiko žyma nepasiekiama. Istorinių laikų kilmė lieka neišsami: negalima manyti, kad ankstesni normalizuoti laikai yra teikėjo laikai. Domeno vardo laiko kilmės apibendrina visus išsaugotus stebėjimus, o ne atskirą pirmą ar paskutinę laiko žymą. Įrašymas Radare ir užfiksuoti patikrinto paskelbimo įrašai naudoja atskirus laikus. Paskelbimo įrašai apima tik naujai sekamus domenų vardus, kurių įrašymo laikas žinomas; ankstesnių domenų vardų, kurių pirmo įrašymo laikas nežinomas, pirmo paskelbimo laikas lieka null. Pirmas užfiksuotas įrašas nuo apskaitos pradžios neįrodo pačios ankstyviausios viešos datos. Nežinomi istoriniai laikai lieka null; sinchronizavimas, importas ar ankstesnė pirmos publikacijos žyma jų nepakeičia. Įrašymo ir paskelbimo rodikliai naudoja savo laikus nepriklausomai nuo stebėjimų laikotarpio."] },
    { eyebrow: "Ankstesnio formato suderinamumo seka", title: "30 dienų įvykių langas", paragraphs: ["Ankstesnio formato kasdieniai neutralizuoti NDJSON įvykiai po nustatyto detalaus laikotarpio sutraukiami į ribotą signalo suvestinę, pagal numatytuosius nustatymus saugomą dvejus metus. Šio suderinamumo vaizdo saugojimo pabaiga neištrina ilgalaikių stebėjimo faktų ir nenustato pagrindinio laikotarpio rinkinio."] },
    { eyebrow: "Būsenos kilmė", title: "Tik aiškūs perėjimai", paragraphs: ["CertStream ir URLScan įrašai lieka įtariami. Perėjimas į aktyvią, nepasiekiamą ar suvaldytą būseną registruojamas tik tada, kai ją pateikia palaikomas HECAVEX stebėjimas. Iškritimas už peržiūrimo laikotarpio ribų nesukuria būsenos perėjimo."] },
    { eyebrow: "Pataisymai", title: "Privačios pastabos lieka privačios", paragraphs: ["HECAVEX operatoriaus peržiūrai naudojama tik papildoma duomenų bazė už Git ribų. Viešą procesą pasiekia tik aiškiai eksportuotos neutralizuotos išimtys ir kandidatai; analitiko pastabos bei tapatybės niekada neįtraukiamos."] },
  ],
  limitationsId: "ribos",
  limitationsEyebrow: "Ribos ir saugumas",
  limitationsTitle: "Signalus vertinti kaip tyrimo kryptis",
  limitationsBody: "Aprėpties spragos ir trūkstamas papildymas yra tikėtini. Nei įrašas Radare, nei jo nebuvimas nėra nuosprendis.",
  limitationCards: [
    { eyebrow: "Interpretavimas", title: "Tyrimo kryptis, ne priskyrimas", paragraphs: ["Eilutė rodo galimą phishing arba apsimetimą. Ji neįrodo kenkėjiško ketinimo, dabartinio pasiekiamumo, nuosavybės, priskyrimo, kompromitavimo ar to, kad asmuo sąveikavo su domenu."] },
    { eyebrow: "Aprėptis", title: "Sąmoningai nepilna", paragraphs: ["Gyvas CertStream srautas atrenkamas, kontroliniais taškais paremta CT paieška priklauso nuo paslaugos indeksavimo ir yra ribota, URLScan pateikia tik jau esamas viešas ataskaitas, o kontekstas neprivalomas. Trūkstami įrodymai nepaverčia kandidato saugiu ir netrukdo pasirodyti nepriklausomai reikalavimus atitinkančiam CT kandidatui."] },
    { eyebrow: "Peradresavimai ir maskavimas", title: "Peradresavimas yra elgsena, ne išteisinimas", paragraphs: ["Pateiktas kandidatas lieka indikatoriumi, kai vieša URLScan ataskaita peradresuoja kitur. Radaras neutralizuotą paskirties vietą įrašo kaip kontekstą, tačiau kandidatui nepriskiria tos paskirties pagrindinio kompiuterio duomenų ar ekrano kopijos. Skirtingi lankytojai gali gauti skirtingą turinį ar peradresavimus."] },
    { eyebrow: "Naršymo sauga", title: "Indikatoriai lieka neutralizuoti", paragraphs: ["Suvestinėje niekada nepateikiamos nuorodos į stebėtus pagrindinius kompiuterius. Įrodymų valdikliai gali kreiptis tik į urlscan.io ir tik naudotojui pasirinkus juos atverti; ataskaitų bei ekrano kopijų URL patikrinami prieš skelbiant."] },
    { eyebrow: "Pataisymai", title: "Taisyklės taikomos iš naujo", paragraphs: ["Sinchronizuojant archyvuoti stebėjimai tikrinami pagal dabartinį registrą, todėl pataisytos prekių ženklų sąsajos ir pridėti oficialūs domenai iš vėlesnių suvestinių pašalina pasenusius klaidingai teigiamus rezultatus."] },
    { eyebrow: "Paslaugos riba", title: "Geriausios pastangos, be SLA", paragraphs: ["HECAVEX prižiūri Radarą kaip geriausiomis pastangomis vykdomą viešą tyrimą. Tai nėra nuolatinė prekių ženklų stebėsena, aukų informavimas, reagavimas į incidentus, turinio šalinimas ar pasiekiamumo bei reagavimo įsipareigojimas."] },
    { eyebrow: "Veikimo įrodymai", title: "Suvestinės būsena turi ribas", paragraphs: ["Šaltinių laiko žymos rodo skelbėjo atliktus archyvų nuskaitymus. Atskirame viešame rinkimo būklės dokumente pateikiamas tik naujausio CertStream bandymo tikras laikas, bendri skaičiai, vėlyvas paleidimas, rezultatas, paskutinė sėkmė ir duomenų naujumas. Kintanti proceso būklė taip pat pateikia neutralizuotas CT paieškos ir DNS bei RDAP vykdymo suvestines; nė vienas iš šių artefaktų neįrodo visiškos pasaulinės aprėpties."] },
    { eyebrow: "IDN rodymas", title: "Kiekviena programa sprendžia atskirai", paragraphs: [<> <a href="https://haveibeensquatted.com/blog/turning-idn-edge-cases-into-typosquats">2026 m. spalio 3 d. IDN tyrime</a> atskirai nagrinėti naršyklės rodymo, navigacijos, registro ir el. pašto programų sprendimai. Tos datos rezultatai neprognozuoja dabartinės programos elgesio. Unicode forma, galiojantis TLS sertifikatas ir perspėjimo nebuvimas saugumo nepatvirtina.</>] },
  ],
  correctionReport: <><span>Manote, kad įrašas neteisingas? </span><a href="mailto:info@hecavex.com?subject=HECAVEX%20Radar%20klaidingas%20teigiamas%20rezultatas">Praneškite apie klaidingai teigiamą rezultatą</a> arba <a href="https://github.com/Hecavex/radar.hecavex.com/issues/new?template=false-positive.yml">sukurkite viešą GitHub pranešimą</a>.</>,
};

export function Methodology({ language = "en" }: { language?: SiteLanguage }) {
  const copy = language === "lt" ? lithuanianCopy : englishCopy;

  return (
    <section className="methodology-section" id="methodology" aria-labelledby="methodology-title">
      <header className="methodology-heading">
        <div><p className="eyebrow">{copy.headingEyebrow}</p><h1 id="methodology-title">{copy.headingTitle}</h1></div>
        <p>{copy.headingBody}</p>
      </header>
      <nav className="methodology-toc" aria-label={copy.tocAriaLabel}>
        <span>{copy.tocLabel}</span><div>{copy.toc.map((item) => <a href={item.href} key={item.href}>{item.label}</a>)}</div>
      </nav>
      <section className="methodology-detail" id={copy.pipelineId} aria-labelledby="pipeline-title">
        <div className="methodology-section-heading"><p className="eyebrow">{copy.pipelineEyebrow}</p><h2 id="pipeline-title">{copy.pipelineTitle}</h2><p>{copy.pipelineBody}</p></div>
        <ol className="methodology-steps" aria-label={copy.pipelineAriaLabel}>{copy.steps.map((step) => <li key={step.number}><span>{step.number}</span><h3>{step.title}</h3><p>{step.body}</p></li>)}</ol>
      </section>
      <section className="methodology-detail" id={copy.collectionId} aria-labelledby="collection-title">
        <div className="methodology-section-heading"><p className="eyebrow">{copy.collectionEyebrow}</p><h2 id="collection-title">{copy.collectionTitle}</h2><p>{copy.collectionBody}</p></div>
        <div className="methodology-source-grid">{copy.collectionCards.map((card) => <article key={card.title}><span>{card.eyebrow}</span><h3>{card.title}</h3>{card.paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}</article>)}</div>
      </section>
      <section className="methodology-detail" id={copy.matchingId} aria-labelledby="matching-title">
        <div className="methodology-section-heading"><p className="eyebrow">{copy.matchingEyebrow}</p><h2 id="matching-title">{copy.matchingTitle}</h2><p>{copy.matchingBody}</p></div>
        <ol className="methodology-rule-list">{copy.matchingRules.map((rule, index) => <li key={rule}><span>{String(index + 1).padStart(2, "0")}</span><p>{rule}</p></li>)}</ol>
        <div className="methodology-note"><strong>{copy.scoreTitle}</strong><p>{copy.scoreBody}</p></div>
      </section>
      <section className="methodology-detail" id={copy.publicationId} aria-labelledby="publication-title">
        <div className="methodology-section-heading"><p className="eyebrow">{copy.publicationEyebrow}</p><h2 id="publication-title">{copy.publicationTitle}</h2><p>{copy.publicationBody}</p></div>
        <dl className="methodology-field-list">{copy.publicFields.map(([term, description]) => <div key={term}><dt>{term}</dt><dd>{description}</dd></div>)}</dl>
        <div className="methodology-note"><strong>{copy.mergeTitle}</strong><p>{copy.mergeBody}</p></div>
        <p className="methodology-report">{copy.publicationReport}</p>
      </section>
      <section className="methodology-detail" id={copy.historyId} aria-labelledby="history-method-title">
        <div className="methodology-section-heading"><p className="eyebrow">{copy.historyEyebrow}</p><h2 id="history-method-title">{copy.historyTitle}</h2><p>{copy.historyBody}</p></div>
        <div className="methodology-boundaries">{copy.historyCards.map((card) => <article key={card.title}><p className="eyebrow">{card.eyebrow}</p><h3>{card.title}</h3>{card.paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}</article>)}</div>
      </section>
      <section className="methodology-detail" id={copy.limitationsId} aria-labelledby="limitations-title">
        <div className="methodology-section-heading"><p className="eyebrow">{copy.limitationsEyebrow}</p><h2 id="limitations-title">{copy.limitationsTitle}</h2><p>{copy.limitationsBody}</p></div>
        <div className="methodology-boundaries">{copy.limitationCards.map((card) => <article key={card.title}><p className="eyebrow">{card.eyebrow}</p><h3>{card.title}</h3>{card.paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}</article>)}</div>
        <p className="methodology-report">{copy.correctionReport}</p>
      </section>
    </section>
  );
}
