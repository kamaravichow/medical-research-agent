"""Canned provider payloads shaped like the real APIs' responses."""

PUBMED_ESEARCH = {"esearchresult": {"count": "2", "idlist": ["38000001", "38000002"]}}

PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
 <PubmedArticle>
  <MedlineCitation>
   <PMID>38000001</PMID>
   <Article>
    <Journal><Title>The New England journal of medicine</Title><ISOAbbreviation>N Engl J Med</ISOAbbreviation>
     <JournalIssue><PubDate><Year>2024</Year><Month>Mar</Month></PubDate></JournalIssue></Journal>
    <ArticleTitle>Empagliflozin in Heart Failure with a Preserved Ejection Fraction: a <i>randomized</i> trial.</ArticleTitle>
    <ELocationID EIdType="doi">10.1056/NEJMoa0000001</ELocationID>
    <Abstract>
     <AbstractText Label="BACKGROUND">SGLT2 inhibitors reduce hospitalization in HFrEF.</AbstractText>
     <AbstractText Label="METHODS">We randomly assigned 5988 patients with class II-IV heart failure to empagliflozin or placebo.</AbstractText>
     <AbstractText Label="RESULTS">The primary outcome occurred in 13.8% vs 17.1% (HR 0.79; 95% CI 0.69-0.90).</AbstractText>
     <AbstractText Label="CONCLUSIONS">Empagliflozin reduced the combined risk of cardiovascular death or hospitalization for heart failure.</AbstractText>
    </Abstract>
    <AuthorList><Author><LastName>Anker</LastName><Initials>SD</Initials></Author><Author><CollectiveName>EMPEROR-Preserved Investigators</CollectiveName></Author></AuthorList>
    <PublicationTypeList><PublicationType>Journal Article</PublicationType><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList>
    <ArticleDate DateType="Electronic"><Year>2024</Year><Month>03</Month><Day>04</Day></ArticleDate>
   </Article>
   <MeshHeadingList><MeshHeading><DescriptorName>Heart Failure</DescriptorName></MeshHeading></MeshHeadingList>
  </MedlineCitation>
  <PubmedData><ArticleIdList><ArticleId IdType="pubmed">38000001</ArticleId><ArticleId IdType="pmc">PMC9000001</ArticleId></ArticleIdList></PubmedData>
 </PubmedArticle>
 <PubmedArticle>
  <MedlineCitation>
   <PMID>38000002</PMID>
   <Article>
    <Journal><Title>Lancet</Title><JournalIssue><PubDate><MedlineDate>2022 Jan-Feb</MedlineDate></PubDate></JournalIssue></Journal>
    <ArticleTitle>SGLT2 inhibitors in patients with heart failure: a comprehensive meta-analysis of five randomised controlled trials.</ArticleTitle>
    <Abstract><AbstractText>Five trials including 21947 participants were pooled. SGLT2 inhibitors reduced cardiovascular death. Interpretation: benefits are consistent across the ejection fraction range.</AbstractText></Abstract>
    <PublicationTypeList><PublicationType>Meta-Analysis</PublicationType><PublicationType>Systematic Review</PublicationType></PublicationTypeList>
   </Article>
  </MedlineCitation>
  <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1016/S0140-0000(22)00001-1</ArticleId></ArticleIdList></PubmedData>
 </PubmedArticle>
</PubmedArticleSet>"""

EUROPEPMC = {
    "resultList": {
        "result": [
            {   # same paper as PubMed 38000001 -> must be merged
                "id": "38000001", "source": "MED", "pmid": "38000001", "doi": "10.1056/NEJMoa0000001",
                "title": "Empagliflozin in Heart Failure with a Preserved Ejection Fraction.",
                "authorString": "Anker SD, Butler J.", "pubYear": "2024", "firstPublicationDate": "2024-03-04",
                "journalInfo": {"journal": {"title": "NEJM", "isoabbreviation": "N Engl J Med"}},
                "isOpenAccess": "N", "citedByCount": 1500,
                "pubTypeList": {"pubType": ["Randomized Controlled Trial", "Journal Article"]},
            },
            {
                "id": "PPR800001", "source": "PPR", "doi": "10.1101/2025.01.01.25000001",
                "title": "Dapagliflozin after acute myocardial infarction: a target trial emulation",
                "authorString": "Lee K, Patel R.", "pubYear": "2025", "firstPublicationDate": "2025-01-05",
                "abstractText": "<h4>Background</h4>Unclear benefit.<h4>Methods</h4>Registry cohort of 45,210 patients.<h4>Conclusions</h4>Dapagliflozin was associated with fewer HF admissions.",
                "isOpenAccess": "Y", "citedByCount": 3,
                "bookOrReportDetails": {"publisher": "medRxiv"},
            },
        ]
    }
}

OPENALEX = {
    "results": [
        {
            "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1016/s0140-0000(22)00001-1",
            "display_name": "SGLT2 inhibitors in patients with heart failure: a comprehensive meta-analysis of five randomised controlled trials",
            "publication_year": 2022, "publication_date": "2022-08-27", "type": "article",
            "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/38000002"},
            "authorships": [{"author": {"display_name": "M Vaduganathan"}}],
            "primary_location": {"source": {"display_name": "The Lancet"}},
            "open_access": {"is_oa": False}, "cited_by_count": 900,
            "abstract_inverted_index": {"Five": [0], "trials": [1], "pooled.": [2]},
        }
    ]
}

CT_STUDY = {
    "protocolSection": {
        "identificationModule": {"nctId": "NCT01234567", "briefTitle": "Empagliflozin After MI", "officialTitle": "A Randomized Trial of Empagliflozin After Acute MI"},
        "statusModule": {"overallStatus": "RECRUITING", "startDateStruct": {"date": "2024-01"},
                         "primaryCompletionDateStruct": {"date": "2027-06"}, "lastUpdatePostDateStruct": {"date": "2099-01-10"}},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Boehringer Ingelheim"}},
        "descriptionModule": {"briefSummary": "Tests empagliflozin vs placebo."},
        "conditionsModule": {"conditions": ["Myocardial Infarction"]},
        "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE3"], "enrollmentInfo": {"count": 6500}},
        "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "Empagliflozin"}]},
        "outcomesModule": {"primaryOutcomes": [{"measure": "Time to HF hospitalization or death", "timeFrame": "2 years"}]},
        "eligibilityModule": {"eligibilityCriteria": "Inclusion: acute MI", "sex": "ALL", "minimumAge": "18 Years"},
        "contactsLocationsModule": {"locations": [{"facility": "Mass General", "city": "Boston", "country": "United States", "status": "RECRUITING"}]},
    },
    "hasResults": False,
}
CLINICALTRIALS = {"studies": [CT_STUDY]}

FDA_LABEL = {
    "results": [{
        "set_id": "abc-123", "effective_time": "20240115",
        "boxed_warning": ["WARNING: PREMATURE DISCONTINUATION INCREASES THROMBOTIC RISK"],
        "indications_and_usage": ["Reduce risk of stroke in nonvalvular AF."],
        "dosage_and_administration": ["5 mg twice daily."],
        "contraindications": ["Active pathological bleeding."],
        "drug_interactions": ["Strong CYP3A4 and P-gp inhibitors."],
        "openfda": {"brand_name": ["ELIQUIS"], "generic_name": ["APIXABAN"], "manufacturer_name": ["BMS"],
                    "route": ["ORAL"], "pharm_class_epc": ["Factor Xa Inhibitor [EPC]"]},
    }]
}
FDA_EVENTS_COUNT = {"results": [{"term": "HAEMORRHAGE", "count": 900}, {"term": "ANAEMIA", "count": 400}]}
FDA_EVENTS_TOTAL = {"meta": {"results": {"total": 5000}}, "results": [{}]}
