## Exon-level coverage for cb-889
1. generate exon-leve bed file intersect with ev6 reportable range
```bash
bedtools intersect -a <(sortBed -i /efs/home/asia.mitchell/projects/GeneCovApp/ref/reportable-range_ev6.bed.gz) -b <(sortBed -i /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exons.bed) > /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/tmp.bed  

bedtools intersect -a <(sortBed -i /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/tmp.bed) -b <(sortBed -i /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exons.bed) -wa -wb | cut -f1,2,3,7 | uniq > /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exons_ev6.bed  
```

2. generate exon-level bed file intersect with ev9 reportable range
```bash
bedtools intersect -a <(sortBed -i /efs/home/asia.mitchell/projects/CB-883/Test/CB-839/reportable-range_ev9.bed.gz) -b <(sortBed -i /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exons.bed) > /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/tmp.bed  

bedtools intersect -a <(sortBed -i /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/tmp.bed) -b <(sortBed -i /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exons.bed) -wa -wb | cut -f1,2,3,7 | uniq > /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exons_ev9.bed  
```

3. Compute metrics for ev8 samples
```bash
N=$(grep -c . /efs/home/asia.mitchell/projects/GeneCovApp/ev8_cov.txt)
qsub -t 1-${N} -tc 50 -q rxlod.q,r2xlod.q,r4xlod.q -v JOB_IMAGE="749961925374.dkr.ecr.us-east-1.amazonaws.com/helix-py-app-covetous:3.0.4-rc.1-ce16cafa2" -cwd -o logs_ev8.out -e logs_ev8.err \
      coverage_stats.py \
      --bed /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exons_ev6.bed \
      --cov-list /efs/home/asia.mitchell/projects/GeneCovApp/ev8_cov.txt \
      --tmp-dir /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exon_tmp/ev8 
      
python coverage_stats.py \
      --bed /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exons_ev6.bed \
      --cov-list /efs/home/asia.mitchell/projects/GeneCovApp/ev8_cov.txt \
      --tmp-dir /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exon_tmp/ev8 \
      --gather -o cb-889/ev8_exon_out_rr.tsv
```
      
4. Compute metrics for ev9 samples
```bash
N=$(grep -c . /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/ev9_cov_300.txt)
qsub -t 1-${N} -tc 50 -q rxlod.q,r2xlod.q,r4xlod.q -v JOB_IMAGE="749961925374.dkr.ecr.us-east-1.amazonaws.com/helix-py-app-covetous:3.0.4-rc.1-ce16cafa2" -cwd -o logs_ev9.out -e logs_ev9.err \
      coverage_stats.py \
      --bed /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exons.bed \
      --cov-list /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/ev9_cov_300.txt \
      --tmp-dir /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exon_tmp/ev9 

python coverage_stats.py \
      --bed /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exons_ev9.bed \
      --cov-list /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/ev9_cov_300.txt \
      --tmp-dir /efs/home/asia.mitchell/projects/GeneCovApp/cb-889/exon_tmp/ev9 \
      --gather -o cb-889/ev9_exon_out.tsv
```

## Coverage for SNPs (starting with a list of rsIDs)
1. make project dir
```bash
mkdir CB-945
```

2. make list of rsids (1 per line)
```bash
awk -F'[,;]' '/rs[0-9]*/ {print $NF}' Appendix_A_05DEC2025.csv > rsids.list
```

3. Get genomic coordinates of rsIDs, make sure bed file is tab separated
```bash
bcftools view --include ID==@rsids.list /efs/home/asia.mitchell/projects/GeneCovApp/ref/All_20180418.vcf.gz -Ou | bcftools query -f '%CHROM %POS %POS %ID{0}\n' > snps1.bed
```

4. increment bed file start position by -1
```bash
awk '{ $2=$2-1; print }' snps2.bed > snps3.bed
```

5. add chr prefix to first column (vi to make sure bed file is tab separated & chrMT == chrM)
```bash
awk '{print "chr" $0}' snps3.bed > snps4.bed
awk -v OFS='\t' '{$1=$1}1' snps4.bed > snps.bed
```

4. Run coverage on SNPs for ev9
```bash
N=$(grep -c . /efs/home/asia.mitchell/projects/GeneCovApp/ev9_cov.txt)
qsub -t 1-${N} -tc 50 -q rxlod.q,r2xlod.q,r4xlod.q -v JOB_IMAGE="749961925374.dkr.ecr.us-east-1.amazonaws.com/helix-py-app-covetous:3.0.4-rc.1-ce16cafa2" -cwd -o logs.out -e logs.err \
      /efs/home/asia.mitchell/projects/GeneCovApp/coverage_stats.py \
      --bed /efs/home/asia.mitchell/projects/CB-945/snps.bed \
      --cov-list /efs/home/asia.mitchell/projects/GeneCovApp/ev9_cov.txt \
      --tmp-dir /efs/home/asia.mitchell/projects/CB-945/cov_tmp/ev9 

python /efs/home/asia.mitchell/projects/GeneCovApp/coverage_stats.py \
      --bed /efs/home/asia.mitchell/projects/CB-945/snps.bed \
      --cram-list /efs/home/asia.mitchell/projects/GeneCovApp/ev9_cov.txt \
      --tmp-dir /efs/home/asia.mitchell/projects/CB-945/cov_tmp/ev9 \
      --gather -o cb-945_ev9_out.tsv

grep -vFf <(awk '{print $1}' cb-945_ev9_out.tsv) rsids.list > missing.rsids 
```
