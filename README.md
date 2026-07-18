# Gene Coverage App

A web application for querying per-gene coverage statistics across a sequencing cohort. Users enter gene names, rsIDs, or genomic coordinates and receive a coverage report. Pre-computed metrics are returned instantly; novel queries are submitted as Hcluster jobs and emailed to the user when complete.

Also includes `coverage_stats.py`, the underlying CLI for computing per-gene coverage metrics from CRAM or `.cov` files.

---

## Architecture

```
Browser (React + TypeScript)
    │  SAML SSO (Okta / Azure AD)
    ▼
FastAPI backend (AWS ECS Fargate)
    ├── PostgreSQL (RDS)          ← pre-computed metrics cache
    ├── GTF + dbSNP VCF (EFS)    ← local annotation for rsID / coordinate lookup
    ├── SSH → Hcluster head node  → coverage_stats.py SGE job array
    └── Amazon SES                → HTML email report on job completion
```

---

## Web App

### Query types

| Input | Example |
|---|---|
| Gene name | `BRCA1` |
| rsID | `rs429358` |
| Genomic coordinate (0-based half-open) | `chr19:44908684-44908822` |

Enter one identifier per line (or comma-separated) in the query form along with your email address, then click **Get Coverage Stats**.

### Response behaviour

- **Cache hit** — gene metrics already exist in the database. Results are displayed immediately in the browser as a coverage table.
- **Cache miss** — gene is not in the database. A `coverage_stats.py` scatter+gather job is submitted to Hcluster. The page shows a live job status panel (polling every 30 s). When the job completes, results are inserted into the database (for future queries) and an HTML report is emailed to the address you provided.

### Coverage metrics reported

| Column | Description |
|---|---|
| `n_samples` | Number of samples in the cohort |
| `min_mean_cov` | Minimum mean depth across all samples (worst-case sample) |
| `max_mean_cov` | Maximum mean depth across all samples |
| `mean_mean_cov` | Mean depth averaged across all samples |
| `min_pct_Nx` | % of bases ≥ depth threshold in the worst-case sample |
| `mean_pct_Nx` | Mean % of bases ≥ depth threshold across all samples |

Default depth threshold: **20x** (configurable via `MIN_DEPTH` env var).

---

## Local Development

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in required values
uvicorn app.main:app --reload
```

Required `.env` variables:

```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/genecoverage
JWT_SECRET=change-me
SAML_SP_ENTITY_ID=https://your-app.example.com
SAML_SP_ACS_URL=https://your-app.example.com/saml/acs
SAML_IDP_METADATA_URL=https://your-idp.example.com/metadata
AWS_REGION=us-east-1
SES_SENDER=noreply@your-domain.com
HCLUSTER_HOST=hcluster-head.internal
HCLUSTER_USER=gcovapp
HCLUSTER_SSH_KEY_PATH=/secrets/hcluster_rsa
HCLUSTER_SCRATCH_DIR=/scratch/gene-coverage-app
HCLUSTER_CRAM_LIST=/efs/cohort/cov_files.txt
GTF_PATH=/efs/ref/gencode.v44.annotation.gtf
DBSNP_VCF_PATH=/efs/ref/All_20180418.vcf.gz
MIN_DEPTH=20
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # proxies /api and /saml to localhost:8000
```

---

## coverage_stats.py CLI

Compute per-gene coverage statistics from CRAM or `.cov` files directly, without the web app.

### Requirements

- Python ≥ 3.6
- `samtools` ≥ 1.9 in `PATH` (CRAM input only)
- `helix_app_covetous` (`.cov` input only)

### Single-node usage

```bash
# CRAM input
python coverage_stats.py --bed regions.bed --cram a.cram b.cram -o out.tsv
python coverage_stats.py --bed regions.bed --cram-list crams.txt -o out.tsv

# .cov input
python coverage_stats.py --bed regions.bed --cov a.cov b.cov -o out.tsv
python coverage_stats.py --bed regions.bed --cov-list covfiles.txt -o out.tsv

# Custom depth threshold
python coverage_stats.py --bed regions.bed --cov-list covfiles.txt --min-depth 10 -o out.tsv
```

### Hcluster (SGE) job array — .cov input

```bash
# Step 1 — scatter (one task per sample)
N=$(grep -c . covfiles.txt)
qsub -t 1-${N} -tc 50 -q rxlod.q,r2xlod.q,r4xlod.q \
    -v JOB_IMAGE="749961925374.dkr.ecr.us-east-1.amazonaws.com/helix-py-app-covetous:3.0.4-rc.1-ce16cafa2" \
    -cwd -o logs.out -e logs.err \
    coverage_stats.py \
    --bed regions.bed \
    --cov-list covfiles.txt \
    --tmp-dir /scratch/cov_tmp

# Step 2 — gather (held on scatter job ID)
python coverage_stats.py \
    --bed regions.bed \
    --cov-list covfiles.txt \
    --tmp-dir /scratch/cov_tmp \
    --gather -o out.tsv
```

### Hcluster (SGE) job array — CRAM input

```bash
N=$(grep -c . crams.txt)
qsub -t 1-${N} -tc 50 -cwd \
    coverage_stats.py \
    --bed regions.bed --cram-list crams.txt \
    --tmp-dir /scratch/cov_tmp [--reference ref.fa]

python coverage_stats.py \
    --bed regions.bed --cram-list crams.txt \
    --tmp-dir /scratch/cov_tmp --gather -o out.tsv
```

---

## Example workflows

### Exon-level coverage for a gene panel

```bash
# 1. Intersect exon BED with reportable range
bedtools intersect \
    -a <(sortBed -i reportable-range_ev6.bed.gz) \
    -b <(sortBed -i exons.bed) \
    > tmp.bed

bedtools intersect \
    -a <(sortBed -i tmp.bed) \
    -b <(sortBed -i exons.bed) \
    -wa -wb | cut -f1,2,3,7 | uniq > exons_ev6.bed

# 2. Run coverage stats across a cohort
N=$(grep -c . ev8_cov.txt)
qsub -t 1-${N} -tc 50 -q rxlod.q,r2xlod.q,r4xlod.q \
    -v JOB_IMAGE="749961925374.dkr.ecr.us-east-1.amazonaws.com/helix-py-app-covetous:3.0.4-rc.1-ce16cafa2" \
    -cwd -o logs_ev8.out -e logs_ev8.err \
    coverage_stats.py \
    --bed exons_ev6.bed \
    --cov-list ev8_cov.txt \
    --tmp-dir exon_tmp/ev8

python coverage_stats.py \
    --bed exons_ev6.bed \
    --cov-list ev8_cov.txt \
    --tmp-dir exon_tmp/ev8 \
    --gather -o ev8_exon_out_rr.tsv
```

### Coverage for a list of rsIDs

```bash
# 1. Extract rsIDs from a manifest
awk -F'[,;]' '/rs[0-9]*/ {print $NF}' Appendix_A.csv > rsids.list

# 2. Look up genomic coordinates from dbSNP
bcftools view --include ID==@rsids.list All_20180418.vcf.gz -Ou \
    | bcftools query -f '%CHROM %POS %POS %ID{0}\n' > snps1.bed

# 3. Convert to 0-based BED with chr prefix
awk '{ $2=$2-1; print }' snps1.bed \
    | awk '{print "chr" $0}' \
    | awk -v OFS='\t' '{$1=$1}1' > snps.bed

# 4. Run coverage stats
N=$(grep -c . ev9_cov.txt)
qsub -t 1-${N} -tc 50 -q rxlod.q,r2xlod.q,r4xlod.q \
    -v JOB_IMAGE="749961925374.dkr.ecr.us-east-1.amazonaws.com/helix-py-app-covetous:3.0.4-rc.1-ce16cafa2" \
    -cwd -o logs.out -e logs.err \
    coverage_stats.py \
    --bed snps.bed \
    --cov-list ev9_cov.txt \
    --tmp-dir cov_tmp/ev9

python coverage_stats.py \
    --bed snps.bed \
    --cov-list ev9_cov.txt \
    --tmp-dir cov_tmp/ev9 \
    --gather -o ev9_snp_out.tsv

# 5. Check for any rsIDs missing from the output
grep -vFf <(awk '{print $1}' ev9_snp_out.tsv) rsids.list > missing.rsids
```

---

## Deployment

Infrastructure is managed with Terraform in `infrastructure/`.

```bash
cd infrastructure
terraform init
terraform plan -var-file=terraform.tfvars
terraform apply -var-file=terraform.tfvars
```

Required `terraform.tfvars` values: `vpc_id`, `private_subnet_ids`, `public_subnet_ids`, `container_image`, `db_password`, `ses_sender_email`.

The backend Docker image is built from `backend/Dockerfile` and pushed to ECR before running `terraform apply`.
