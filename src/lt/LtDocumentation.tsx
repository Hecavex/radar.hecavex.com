const flow = [
  ["01", "Surinkti", "Riboti Python rinktuvai skaito pasyvius sertifikatų įvykius ir jau paskelbtas viešas ataskaitas."],
  ["02", "Archyvuoti", "Patikrinti ir neutralizuoti stebėjimai saugomi pagal datą suskirstytuose NDJSON failuose."],
  ["03", "Sinchronizuoti", "Leidėjas iš naujo patikrina, apriboja, sujungia ir atominiu būdu įrašo viešus duomenis."],
  ["04", "Atvaizduoti", "Statinė React sąsaja patikrina suvestinės struktūrą ir pateikia tik skaitymui skirtus vaizdus."],
] as const;

const sources = [
  ["CertStream", "Atrankinis tiesioginis Certificate Transparency įvykių klausymas suplanuotais langais.", "Dalis įvykių už klausymosi langų gali būti nepastebėta."],
  ["Ribota CT paieška", "Kontroliniais taškais paremta crt.sh paieška pagal peržiūrėtus prekių ženklų terminus.", "Indeksavimas, užklausų ribos ir ribotas terminų rinkinys mažina aprėptį."],
  ["URLScan", "Tik jau egzistuojančių viešų rezultatų paieška ir viešų detalių gavimas.", "Radaras nepateikia naujo skenavimo; rezultato nebuvimas nėra saugumo požymis."],
  ["HECAVEX", "Pasirinktinė, aiškiai sukonfigūruota ir prieš skelbimą neutralizuota vieša įvestis.", "Vidiniai šaltiniai, analitiko užrašai ir privati istorija nėra skelbiami."],
  ["DNS ir RDAP", "Ribotas jau paskelbtų kandidatų domeno ir registracijos kontekstas.", "Bendra infrastruktūra yra sąsaja, o ne savininko ar veikėjo priskyrimas."],
] as const;

const fields = [
  ["id", "Deterministinis 20 šešioliktainių simbolių signalo identifikatorius."],
  ["url / domain", "Normalizuotas ir neutralizuotas HTTP(S) indikatorius bei domenas; prisijungimo duomenys, užklausos ir fragmentai pašalinami."],
  ["firstSeen / lastSeen", "Ankstyviausias ir vėliausias priimto stebėjimo laikas UTC."],
  ["sources", "Pasikartojimų neturintis šaltinių sąrašas: CertStream, URLScan arba HECAVEX."],
  ["status", "Gyvavimo ciklo būsena; automatizuoti CertStream ir URLScan įrašai lieka įtariami."],
  ["brand", "Pagal registrą nustatytas galimas prekių ženklas, o ne grėsmės veikėjo priskyrimas."],
  ["country / host", "Stebėtas prieglobos kontekstas, o ne operatoriaus vieta ar tapatybė."],
  ["matchScore", "0–100 taisyklių atitikimo balas; ne tikimybė, pasitikėjimas ar kenkėjiškumo nuosprendis."],
  ["evidenceTier", "Tik pavadinimo, papildomai patvirtintas arba analitiko peržiūrėtas įrodymų lygis."],
  ["reasonCodes", "Kontroliuojamos įtraukimo priežastys ir kilmės žymos, o ne įrodymai apie ketinimą."],
] as const;

const operations = [
  ["CertStream rinkimas", "08, 23, 38 ir 53 minutę kiekvieną UTC valandą", "Kandidatų archyvas ir naujausio bandymo būklė"],
  ["Kontroliniais taškais paremta CT paieška", "43 minutę kiekvieną UTC valandą", "Peržiūrėtų terminų žymekliai ir CT kandidatai"],
  ["URLScan paieška", "37 minutę kas antrą UTC valandą", "Ribota paieškos būsena ir vieši rezultatai"],
  ["Oficialių išteklių pivot", "03:47 ir 15:47 UTC", "Kolizijas atmetančios pirmosios šalies maišos ir savarankiškai pagrįsti vieši rezultatai"],
  ["DNS ir RDAP kontekstas", "01:13, 07:13, 13:13 ir 19:13 UTC", "Jau paskelbtų kandidatų ribotas kontekstas"],
  ["Laikinio konteksto atnaujinimas", "01:31, 07:31, 13:31 ir 19:31 UTC", "Ribotos DNS, RDAP ir maršrutizavimo bazės bei pokyčių žurnalas"],
  ["Suvestinės sinchronizavimas", "17 minutę kiekvieną UTC valandą; iškart po kandidatų aptikusio rinkimo", "Suvestinės, dalijimosi failai, istorija, kokybė, aprėptis ir peržiūros eilė"],
  ["Puslapių paskelbimas", "Patikrintas kodas, pakeista vieša suvestinė arba rinktuvo klaida", "Statinis GitHub Pages artefaktas"],
  ["Duomenų srauto būklė", "11 minutę kas antrą UTC valandą", "Vienas deduplikuotas GitHub Issue, uždaromas sistemai atsistačius"],
  ["Neutralizuotas peržiūros pasiūlymas", "Tik prižiūrėtojo rankinis paleidimas", "Juodraštinis pull request; ne analitiko sprendimas"],
  ["Savaitinis duomenų paketas", "Pirmadienį 06:29 UTC", "Po išorinių vartų: archyvas, manifestas, SPDX 2.3, kontrolinės sumos ir atestacijos"],
] as const;

const settings = [
  ["URLSCAN_API_KEY", "GitHub Secret", "Tik pasyviai esamų viešų URLScan rezultatų paieškai ir gavimui."],
  ["URLSCAN_DERIVED_REDISTRIBUTION_CONFIRMED", "GitHub Variable", "Tiksli reikšmė true leidžia URLScan kilmės laikinį kontekstą tik patvirtinus platinimo teisę."],
  ["PASSIVE_CONTEXT_*", "GitHub Variables", "Riboja rotaciją, RIPEstat podėlį, URLScan amžių, pokyčių saugojimą, RPKI ir vykdymo laiką."],
  ["RADAR_MISP_FEED_ENABLED", "GitHub Variable", "Įjungiamas tik realiam MISP 2.5 importui ir trynimo tombstone elgsenai praėjus patikrą."],
  ["RADAR_IMMUTABLE_RELEASES_CONFIRMED", "GitHub Variable", "Nustatomas tik įjungus GitHub Release immutability; pats kintamasis jos neįjungia."],
  ["VIRUSTOTAL_API_KEY", "GitHub Secret", "Pasirinktinei vieno jau paskelbto signalo prižiūrėtojo patikrai; ne rinkimo ar balų šaltinis."],
  ["GOOGLE_SAFE_BROWSING_API_KEY", "Tik privati vietinė aplinka", "Nenaudojamas viešuose Actions; rezultatai vietoje saugomi iki tiekėjo nurodyto galiojimo pabaigos."],
] as const;

export function LtDocumentation() {
  return <article className="docs-content" aria-labelledby="documentation-title">
    <header className="docs-heading">
      <div><p className="eyebrow">Pagrindinė dokumentacija</p><h1 id="documentation-title">HECAVEX Radaro techninis žinynas</h1></div>
      <p>Architektūra, šaltinių veikimas, viešos schemos, eksploatavimo ribos ir duomenų sąlygos, taikomos HECAVEX prižiūrimai paslaugai radar.hecavex.com. Aptikimo metodika atskirai aprašyta <a href="/lt/metodologija/">metodologijos puslapyje</a>.</p>
    </header>

    <nav className="docs-toc" aria-label="Dokumentacijos skyriai"><span>Turinys</span><div>
      <a href="#architektura">Architektūra</a><a href="#saltiniai">Šaltiniai</a><a href="#viesi-duomenys">Vieši duomenys</a><a href="#stix">STIX</a><a href="#duomenu-sutartis">Duomenų sutartis</a><a href="#istorija">Istorija</a><a href="#veikimas">Veikimas</a><a href="#saugumas">Saugumas</a><a href="#duomenu-salygos">Duomenų sąlygos</a>
    </div></nav>

    <section className="docs-section" id="architektura"><div className="docs-section-heading"><p className="eyebrow">Architektūra</p><h2>Python duomenų srautas, statinė sąsaja</h2><p>Naršyklė neturi programų serverio, paskyrų sistemos ar tiesioginio ryšio su duomenų baze.</p></div>
      <ol className="docs-flow" aria-label="Radaro duomenų srautas">{flow.map(([number, title, body]) => <li key={number}><span>{number}</span><h3>{title}</h3><p>{body}</p></li>)}</ol>
      <div className="docs-callout"><strong>Skelbimo riba</strong><p>Tik sinchronizavimo procesas rašo viešą suvestinę. Neprieinamas pasirinktinis šaltinis negali ištrinti sveikų šaltinių duomenų, o netikėtas staigus sumažėjimas sustabdo skelbimą.</p></div>
    </section>

    <section className="docs-section" id="saltiniai"><div className="docs-section-heading"><p className="eyebrow">Šaltiniai</p><h2>Ką kiekvienas šaltinis gali pagrįsti</h2><p>Šaltinio etiketė aprašo stebėjimo kilmę. Ji nereiškia patvirtinto kenkėjiškumo.</p></div>
      <div className="docs-table-wrap" role="region" aria-label="Duomenų šaltinių semantika" tabIndex={0}><table className="docs-table"><thead><tr><th>Šaltinis</th><th>Naudojimas</th><th>Aprėpties riba</th></tr></thead><tbody>{sources.map(([name, use, limit]) => <tr key={name}><th scope="row">{name}</th><td>{use}</td><td>{limit}</td></tr>)}</tbody></table></div>
    </section>

    <section className="docs-section" id="viesi-duomenys"><div className="docs-section-heading"><p className="eyebrow">Vieši duomenys</p><h2>Vienas skelbimo rinkinys, keli vaizdai</h2><p>Skydelis, istorija, įvykių žurnalas, STIX ir atsisiunčiami JSON failai kuriami iš tos pačios patikrintos publikavimo ribos.</p></div>
      <div className="docs-card-grid">
        <article><h3>Dabartinė suvestinė</h3><p>Ribotas naujausių priimtų kandidatų vaizdas. Eilutės neutralizuotos ir nėra automatinis blokavimo sąrašas.</p><a href="/data/radar.json">Atverti radar.json</a></article>
        <article><h3>Išsaugota istorija</h3><p>Pirmo ir paskutinio stebėjimo laikas, stebėjimų skaičius ir tik aiškiai užfiksuoti būsenos pokyčiai.</p><a href="/history/">Atverti istoriją anglų kalba</a><a href="/data/history.json">Atverti history.json</a></article>
        <article><h3>Įvykių žurnalas</h3><p>Pirmosios publikacijos, pakartotiniai stebėjimai, būsenos pokyčiai ir aiškūs atšaukimai.</p><a href="/lt/pokyciai/">Atverti pokyčius</a><a href="/data/feed-manifest.json">Atverti srautų manifestą</a></article>
        <article><h3>Peržiūrėto MISP manifestas</h3><p>Manifestas gali rodyti tik galiojantį analitiko patvirtinimą. Tuščias objektas yra teisingas rezultatas, kol tokio įrašo nėra; MISP importas dar nėra laikomas priimtu.</p><a href="/data/misp/manifest.json">Atverti MISP manifestą</a></article>
        <article><h3>Oficialių domenų warning list</h3><p>Atskiras MISP sąrašas kuriamas iš peržiūrėto registro. Sutapimas perspėja apie galimą klaidingą teigiamą rezultatą, bet neįrodo, kad visas subdomenas yra saugus.</p><a href="/data/misp-warninglists/hecavex-official-domains/list.json">Atverti warning list</a></article>
        <article><h3>Ataskaitos įrodymų įrankis</h3><p>Naršyklėje galima paruošti ribotą failą vienam galiojančiam peržiūrėtam signalui. Įrankis nekuria sprendimo, nesikreipia į kandidatą ir nieko neišsiunčia.</p><a href="/reporting/">Atverti įrankį</a></article>
      </div>
    </section>

    <section className="docs-section" id="stix"><div className="docs-section-heading"><p className="eyebrow">STIX 2.1</p><h2>Stebėjimai atskirti nuo patvirtintų indikatorių</h2><p>Vieša projekcija nėra TAXII paslauga ir nėra skirta automatiniam blokavimui.</p></div>
      <div className="docs-card-grid"><article><h3>Stebėjimų rinkinys</h3><p><code>radar.stix.json</code> pateikia galimų arba įtariamų domenų vardų stebėjimus su aiškiomis ribomis.</p><a href="/data/radar.stix.json">Atsisiųsti STIX stebėjimus</a></article><article><h3>Peržiūrėtas rinkinys</h3><p><code>radar-reviewed.stix.json</code> gali turėti tik aiškiai ir laikinai analitiko patvirtintus indikatorius.</p><a href="/data/radar-reviewed.stix.json">Atsisiųsti peržiūrėtą STIX</a></article></div>
    </section>

    <section className="docs-section" id="duomenu-sutartis"><div className="docs-section-heading"><p className="eyebrow">Duomenų sutartis</p><h2>Stabilūs viešos suvestinės laukai</h2><p>Trūkstama pasirenkama reikšmė reiškia nežinomybę, o ne neigiamą išvadą.</p></div>
      <div className="docs-table-wrap" role="region" aria-label="Viešos suvestinės laukų žinynas" tabIndex={0}><table className="docs-table"><thead><tr><th>Laukas</th><th>Reikšmė</th></tr></thead><tbody>{fields.map(([term, description]) => <tr key={term}><th scope="row"><code>{term}</code></th><td>{description}</td></tr>)}</tbody></table></div>
      <div className="docs-callout"><strong>Unicode ir atitikčių testai</strong><p>Domenai normalizuojami prisegtu UTS #46 nontransitional STD3 režimu, o UTS #39 duomenys naudojami tik ribotiems confusable ir rašto įrodymams. Vidinis skeleton neskelbiamas, Unicode sutapimas vienas pats nėra phishing nuosprendis, o <code>restricted-identifier</code> yra konservatyvi Radaro taisyklė, ne formalus Unicode restriction level. Versijuotas sintetinių, rezervuotų ir oficialių domenų korpusas tikrinamas CI.</p></div>
      <div className="docs-callout"><strong>Atskiri IDN vaizdiniai paaiškinimai</strong><p>Ribotas <a href="/data/idn-matches-v1.json">IDN paaiškinimų failas</a> naudoja profilį <code>radar-idn-visual-v1</code> ir susieja kiekvieną peržiūrėtą pakaitą su dabartiniu paskelbtu signalu, registro pavadinimu bei Unicode kodo taško vieta. Vaizdinis panašumas atskirtas nuo tikslaus UTS #39 sutapimo. Jis neįrodo kenkėjiškumo, naršyklės rodymo ar analitiko peržiūros; vidinės skeleton eilutės neskelbiamos. Suvestinė išlaiko esamą 2 versijos žodyną.</p></div>
      <div className="docs-card-grid"><article><h3>Prekių ženklų aprėpties žurnalas</h3><p>Rodo registro peržiūros datą, ribotą rinktuvų būklę, matcher korpuso aprėptį ir viešos peržiūros rezultatus. Tai nėra phishing paplitimo matas.</p></article><article><h3>Subalansuota peržiūros eilė</h3><p>Kandidatai deterministiškai paskirstomi pagal šaltinį, ženklą, balą, įrodymus, priežastį ir amžių. Tai nėra atsitiktinė imtis ar analitiko sprendimas.</p></article></div>
    </section>

    <section className="docs-section" id="istorija"><div className="docs-section-heading"><p className="eyebrow">Istorija ir peržiūra</p><h2>Įvykiai pridedami, o nebuvimas neinterpretuojamas</h2><p>Pakartotinai apdorojant tuos pačius archyvus deterministiniai įvykių ID neleidžia dirbtinai didinti skaičių.</p></div>
      <div className="docs-card-grid"><article><h3>Detalus laikotarpis</h3><p>Pagal datą suskirstyti įvykiai numatytą laiką lieka detalūs, vėliau sutraukiami į ribotą signalo istoriją.</p></article><article><h3>Būsenos kilmė</h3><p>Dingimas iš naujausio lango nesukuria būsenos pokyčio. Aktyvi, nepasiekiama ar suvaldyta būsena reikalauja palaikomo aiškaus stebėjimo.</p></article><article><h3>Analitiko peržiūra</h3><p>Vidiniai užrašai ir tapatybės lieka už Git ribų. Viešai pateikiami tik sąmoningai eksportuoti ir neutralizuoti sprendimai.</p></article><article><h3>Sanitized pasiūlymas nėra sprendimas</h3><p>Prižiūrėtojo workflow gali sukurti tik ribotą proposal failą ir juodraštinį pull request. Sinchronizavimą veikia tik atskirai eksportuotas viešas sprendimas.</p></article></div>
    </section>

    <section className="docs-section" id="veikimas"><div className="docs-section-heading"><p className="eyebrow">Veikimas</p><h2>Suplanuoti darbai ir jų vieši rezultatai</h2><p>Grafikas aprašo numatytą pradžią, o ne garantuotą nenutrūkstamą aprėptį. Įprasti tik rinktuvo pakeitimai laukia valandinio suvestinės sinchronizavimo. Kandidatų aptikęs rinkimas sinchronizavimą paleidžia iškart, o rinktuvo klaidos būklė gali būti paskelbta tiesiogiai.</p></div>
      <div className="docs-table-wrap" role="region" aria-label="Suplanuoti Radaro darbai" tabIndex={0}><table className="docs-table"><thead><tr><th>Darbas</th><th>Grafikas</th><th>Viešas rezultatas</th></tr></thead><tbody>{operations.map(([name, schedule, result]) => <tr key={name}><th scope="row">{name}</th><td>{schedule}</td><td>{result}</td></tr>)}</tbody></table></div>
      <div className="docs-callout"><strong>Kontroliniai taškai ir laikinas kontekstas</strong><p><code>data/urlscan/search-checkpoints.json</code> saugo tik užklausos maišą, tiekėjo žymeklį, ribotą rezultatų skaičių ir pažangos būseną; užklausos tekstas nesaugomas, o klaida ar išnaudotas biudžetas negali pažymėti eilės užbaigta. <code>data/enrichment/passive-context.json</code> ir <code>data/history/context/</code> saugo ribotas DNS, RDAP ir maršrutizavimo bazes bei semantinius pokyčius. Viešą naujausio bandymo ir leidybos būklę pateikia <a href="/data/collection-health.json">collection-health.json</a> ir <a href="/data/pipeline-health.json">pipeline-health.json</a>.</p></div>
      <h3 className="docs-subheading">Repozitorijos nustatymai ir išoriniai vartai</h3>
      <div className="docs-table-wrap" role="region" aria-label="Radaro repozitorijos nustatymai" tabIndex={0}><table className="docs-table"><thead><tr><th>Nustatymas</th><th>Tipas</th><th>Paskirtis</th></tr></thead><tbody>{settings.map(([name, kind, purpose]) => <tr key={name}><th scope="row"><code>{name}</code></th><td>{kind}</td><td>{purpose}</td></tr>)}</tbody></table></div>
      <div className="docs-callout docs-warning-callout"><strong>Išorinės patikros dar nėra automatinis faktas</strong><p>Dabartinėje viešoje imtyje nėra užbaigtų analitiko vertinimų, todėl tikslumo rodiklis nerodomas, o peržiūrėtas MISP manifestas pagrįstai tuščias. URLScan kilmės laikiniai duomenys lieka išjungti iki platinimo teisės patvirtinimo. MISP importas, tombstone elgsena ir GitHub taisyklės, reikalaujančios CI bei peržiūros, turi būti patikrinti operatoriaus; CODEOWNERS ir vietinis schemos testas šių vartų nepakeičia.</p></div>
    </section>

    <section className="docs-section" id="saugumas"><div className="docs-section-heading"><p className="eyebrow">Saugumas</p><h2>Neutrali, tik skaitymui skirta vieša sąsaja</h2><p>Radaro puslapiai nevykdo kandidatų turinio ir nepaverčia neutralizuotų indikatorių tiesioginėmis nuorodomis.</p></div>
      <div className="docs-card-grid"><article><h3>Įvesties ribos</h3><p>Vieši duomenys tikrinami pagal schemą, dydžio ribas, leidžiamus protokolus ir kontroliuojamas reikšmes.</p></article><article><h3>Išorinės nuorodos</h3><p>Įrodymų nuorodos leidžiamos tik į patikrintus viešus URLScan išteklius ir atveriamos tik naudotojui pasirinkus.</p></article><article><h3>Vietinis IOC įrankis</h3><p>Įklijuotos reikšmės ir failai apdorojami naršyklės atmintyje, neįkeliami į HECAVEX ir išnyksta atnaujinus ar užvėrus puslapį.</p></article></div>
    </section>

    <section className="docs-section" id="duomenu-salygos"><div className="docs-section-heading"><p className="eyebrow">Duomenų sąlygos</p><h2>Gynybinis tyrimas, ne reputacijos paslauga</h2><p>Duomenys skelbiami geriausiomis pastangomis ir be stebėjimo, pranešimo, reagavimo, pašalinimo ar pasiekiamumo SLA.</p></div>
      <div className="docs-callout"><strong>Naudokite kaip tyrimo kryptį</strong><p>Įtraukimas neįrodo kenkėjiškumo, o nebuvimas neįrodo saugumo. Prieš blokavimą ar viešą teiginį patikrinkite šaltinį, laiką, kontekstą ir įrodymų lygį.</p></div>
      <p className="methodology-report">Apie galimą klaidingą teigiamą rezultatą praneškite adresu <a href="mailto:info@hecavex.com?subject=HECAVEX%20Radar%20klaidingas%20teigiamas%20rezultatas">info@hecavex.com</a>, nurodydami signalo ID ir patikrinamą pagrindimą.</p>
    </section>
  </article>;
}
