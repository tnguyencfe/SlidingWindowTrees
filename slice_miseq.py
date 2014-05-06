import sam_handler
import os
import subprocess
import StringIO
import Utility
import csv
import glob


HYPHY_TSV_DN_COL = 'dN'
HYPHY_TSV_DS_COL = 'dS'
HYPHY_TSV_S_COL = 'Observed S Changes'
HYPHY_TSV_N_COL = 'Observed NS Changes'
HYPHY_TSV_SCALED_DN_MINUS_DS_COL = 'Scaled dN-dS'
HYPHY_TSV_PROB_FULLSEQ_S_COL = 'P{S leq. observed}'
HYPHY_TSV_NEG_PROB_FULLSEQ_S_COL = 'P{S geq. observed}'



NUC_PER_CODON = 3


class SiteDnDsInfo:
    def __init__(self):
        self.accum_win_dnds = 0.0
        self.accum_win_dn_minus_ds = 0.0
        self.total_win_cover_site = 0
        self.total_syn_subs = 0
        self.total_nonsyn_subs = 0
        self.total_reads = 0

    def add_dnds(self, dnds, dn_minus_ds, reads, syn_subs, nonsyn_subs):
        self.total_win_cover_site += 1
        if dnds is not None:
            self.accum_win_dnds += dnds
        self.accum_win_dn_minus_ds += dn_minus_ds
        self.total_reads += reads
        self.total_syn_subs += syn_subs
        self.total_nonsyn_subs += nonsyn_subs

    def get_ave_dnds(self):
        if not self.total_win_cover_site:
            return None
        else:
            return self.accum_win_dnds / self.total_win_cover_site

    def get_ave_dn_minus_ds(self):
        if not self.total_win_cover_site:
            return None
        else:
            return self.accum_win_dn_minus_ds / self.total_win_cover_site


    def get_window_coverage(self):
        return self.total_win_cover_site

    def get_ave_read_coverage(self):
        if not self.total_win_cover_site:
            return None
        else:
            return float(self.total_reads)/self.total_win_cover_site

    def get_ave_syn_subs(self):
        if not self.total_win_cover_site:
            return None
        else:
            return float(self.total_syn_subs)/self.total_win_cover_site

    def get_ave_nonsyn_subs(self):
        if not self.total_win_cover_site:
            return None
        else:
            return float(self.total_nonsyn_subs)/self.total_win_cover_site

    def get_ave_subs(self):
        if not self.total_win_cover_site:
            return None
        else:
            return float(self.total_nonsyn_subs + self.total_syn_subs)/self.total_win_cover_site

class SeqDnDsInfo:
    """
    A sequence of Dn/Ds by site
    """
    def __init__(self, seq_len):
        """
        Constructor.

        :rtype SeqDnDsInfo :  instance object
        :param int seq_len: total codons in the sequence
        """
        self.dnds_seq = [SiteDnDsInfo() for i in range(seq_len)]

    def add_site_dnds(self, site_1based, dnds, dn_minus_ds, reads, syn_subs, nonsyn_subs):
        """
        Keep track of dn/ds from a window containing this site.
        :param site_1based: 1-based codon site
        :param dnds: dn/ds for this codon site as determined from a window fed into hyphy
        """
        self.dnds_seq[site_1based-1].add_dnds(dnds=dnds, dn_minus_ds=dn_minus_ds, reads=reads, syn_subs=syn_subs, nonsyn_subs=nonsyn_subs)

    def get_site_ave_dnds(self, site_1based):
        return self.dnds_seq[site_1based-1].get_ave_dnds()

    def get_site_ave_dn_minus_ds(self, site_1based):
        return self.dnds_seq[site_1based-1].get_ave_dn_minus_ds()

    def get_seq_len(self):
        return len(self.dnds_seq)

    def get_site_window_cov(self, site_1based):
        return self.dnds_seq[site_1based-1].get_window_coverage()

    def get_site_ave_read_cov(self, site_1based):
        return self.dnds_seq[site_1based-1].get_ave_read_coverage()

    def get_site_ave_syn_subs(self, site_1based):
        return self.dnds_seq[site_1based-1].get_ave_syn_subs()

    def get_site_ave_nonsyn_subs(self, site_1based):
        return self.dnds_seq[site_1based-1].get_ave_nonsyn_subs()

    def get_site_ave_subs(self, site_1based):
        return self.dnds_seq[site_1based-1].get_ave_subs()


def __get_window_seq(seq, start_pos, end_pos, breadth_thresh=0.0):
    """
    If the sequence fits the window constraints, then returns the sliced sequence.
    Otherwise returns None.

    :rtype str :  Sequence that fits in the window, right padded if necessary.  None if sequence doesn't fit window constraints.
    :param seq str: sequence with no newlines
    :param start_pos int: 1-based
    :param end_pos int : 1-based
    :param breadth_thresh float: fraction of sequence that be A,C,T,or G within start_pos and end_pos inclusive.
    """
    if seq and len(seq) >= start_pos:
        slice_seq = seq[start_pos-1:end_pos]
        slice_seq_uc = slice_seq.upper()
        a_count = slice_seq_uc.count('A')
        t_count = slice_seq_uc.count('T')
        g_count = slice_seq_uc.count('G')
        c_count = slice_seq_uc.count('C')
        if float(a_count+g_count+c_count+t_count)/(end_pos - start_pos + 1) >= breadth_thresh:
            pad = '-' * max(0, end_pos - len(seq))
            return slice_seq

    return None


def create_slice_msa_fasta(fasta_filename, out_fasta_filename, start_pos, end_pos, breadth_thresh=0.0):
    """
    From a fasta file of multiple sequence alignments, extract the sequence sequence from desired region.
    Writes the extracted sequences into a new fasta file with ".<start_pos>_<end_pos>.fasta" suffix.
    If the sequence is shorter than <end_pos>, then fills in the gaps with '-' characters so that it ends at <end_pos>

    Only puts in the read into the sliced msa fasta if it obeys the window constraints.

    :rtype int: total sequences written
    :param str fasta_filename: full file path to fasta of multiple sequence alignments
    :param str out_fasta_filename:  full file path to output fasta of sliced multiple sequence alignments
    :param int start_pos : 1-based start position of region to extract
    :param int end_pos: 1-based end position of region to extract
    :param float breadth_thresh: fraction of sequence that be A,C,T,or G within start_pos and end_pos inclusive.
    """

    total_seq = 0
    with open(fasta_filename, 'r') as fasta_fh, open(out_fasta_filename, 'w') as slice_fasta_fh:
        header = ""
        seq = ""
        for line in fasta_fh:
            line = line.rstrip()
            if line:
                line = line.split()[0]  # remove trailing whitespace and any test after the first whitespace

                if line[0] == '>':  # previous sequence is finished.  Write out previous sequence
                    window_seq = __get_window_seq(seq=seq, start_pos=start_pos, end_pos=end_pos, breadth_thresh=breadth_thresh)
                    if window_seq:
                        slice_fasta_fh.write(header + "\n")
                        slice_fasta_fh.write(window_seq + "\n")
                        total_seq += 1

                    seq = ""
                    header = line

                else:   # cache current sequence so that entire sequence is on one line
                    seq += line

        window_seq = __get_window_seq(seq=seq, start_pos=start_pos, end_pos=end_pos, breadth_thresh=breadth_thresh)
        if window_seq:
            slice_fasta_fh.write(header + "\n")
            slice_fasta_fh.write(window_seq + "\n")
            total_seq += 1

    return total_seq


def get_best_window_size_from_sam(sam_filename, ref_filename, depth_thresh, breadth_thresh, min_size):
    """
    Create index reference file.
    Create sorted, indexed bam file from sam file.
    Create depth file from bam file.
    Slide through the alignments for every sequence in the reference file.
    The smallest window size is selected such that for every window of that size along the genome,
    the window is covered by at least <min_reads> that cover <breadth_cov_thresh> fraction of the window.

    :rtype int :  best window size in bases or -1 if there are none that meet the constraints
    :param sam_filename: full file path to the sam alignment file
    :param ref_filename: full file path to the reference file
    :param float breadth_thresh : fraction of window that reads must cover
    :param int depth_thresh: minimum number of reads in window that must cover <breadth_cov_thresh> fraction of the window
    :param int min_size: minimum number of bases allowed in the window.
    """

    # convert sam to bam
    bam_filename = sam_handler.sam_to_sort_bam(sam_filename=sam_filename, ref_filename=ref_filename)

    # create depth file for all references
    depth_filename = sam_handler.create_depth_file_from_bam(bam_filename=bam_filename)

    best_size = get_best_window_size_from_depthfile(sorted_bam_filename=bam_filename,
                                                    depth_filename=depth_filename,
                                                    ref_fasta_filename=ref_filename,
                                                    depth_thresh=depth_thresh, breadth_thresh=breadth_thresh, min_size=min_size)

    return best_size


def get_longest_consec_base_below_depth(depth_filename, ref_fasta_filename, depth_thresh):
    """
    In order for a window to be valid, it must be have at least depth_thresh reads that cover
    <breadth_cov_thresh> fraction of the window.

    The largest window size possible is the size of the longest reference contig.
    If the longest stretch of consecutive bases with unacceptable depth coverage
    is larger than the breadth_thres * largest possible window size,
    then there are no valid windows.

    :rtype int: total consecutive bases below the specified depth
    :param depth_filename:  full path to samtools depth file
    :param ref_fasta_filename: full path to reference fasta file
    :param depth_thresh: minimum reads that must exist in the window that cover breadth_thresh fraction of the window.
    :param breadth_thresh:  minimum fraction of window that must be covered by at least depth_thresh reads.
    """
    # is_valid = False
    with open(depth_filename, 'r') as depth_fh:

        # Assume that depth file is sorted by reference, then position
        # Assume position is 1-based.
        # Assume that the depth file skips bases with zero coverage.
        last_ref = ''
        last_pos = 0
        longest_consec_base_below_depth = 0
        consec_base_below_depth = 0
        for line in depth_fh:
            ref, pos, depth = line.rstrip().split()  # pos is 1-based
            if depth < depth_thresh:
                if last_ref != ref:
                    longest_consec_base_below_depth = max(longest_consec_base_below_depth, consec_base_below_depth)
                    consec_base_below_depth = 0

                consec_base_below_depth += (pos - last_pos)

            else:
                longest_consec_base_below_depth = max(longest_consec_base_below_depth, consec_base_below_depth)
                consec_base_below_depth = 0

            last_ref = ref
            last_pos = pos

        max_poss_windowsize = Utility.get_longest_seq_size_from_fasta(fasta_filename=ref_fasta_filename)

        # if longest_consec_base_below_depth <= (breadth_thresh * max_poss_windowsize):
        #     is_valid = True

    return longest_consec_base_below_depth


def is_window_size_valid(depth_filename, ref_fasta_filename, depth_thresh, breadth_thresh, window_size):

    with open(depth_filename, 'r') as depth_fh:

        # Assume that depth file is sorted by reference, then position
        # Assume position is 1-based.
        # Assume that the depth file skips bases with zero coverage.
        last_ref = ''
        last_pos = 0
        longest_consec_base_below_depth = 0
        consec_base_below_depth = 0
        for line in depth_fh:
            ref, pos, depth = line.rstrip().split()  # pos is 1-based
            if depth < depth_thresh:
                if last_ref != ref:
                    longest_consec_base_below_depth = max(longest_consec_base_below_depth, consec_base_below_depth)
                    consec_base_below_depth = 0

                consec_base_below_depth += (pos - last_pos)

            else:
                longest_consec_base_below_depth = max(longest_consec_base_below_depth, consec_base_below_depth)
                consec_base_below_depth = 0

            last_ref = ref
            last_pos = pos

def get_best_window_size_from_depthfile(sorted_bam_filename, depth_filename, ref_fasta_filename, depth_thresh, breadth_thresh, min_size):
    """
    Slide through the alignments for every sequence in the reference file.
    Find the window size such that the smallest window size is selected such that
    for every window of that size along the genome,
    the window is covered by at least <min_reads> that cover <breadth_cov_thresh> fraction of the window.

    :rtype int :  best window size in bases or -1 if there is no window size that meets the constraints
    :param str sorted_bam_filename: full file path to bam file sorted by left coordinates
    :param str depth_filename: full file path to the samtools depth file
    :param str ref_fasta_filename: full file path to the reference fasta file
    :param float breadth_thresh : fraction of window that reads must cover
    :param int depth_thresh: minimum number of reads in window that cover at least <breadth_thresh> fraction of the window
    :param int min_size: minimum number of bases allowed in the window.
    """

    best_size = 1

    # Find the smallest possible window size
    size_bad_cov = get_longest_consec_base_below_depth(depth_filename=depth_filename, ref_fasta_filename=ref_fasta_filename,
                                                   depth_thresh=depth_thresh)
    windowsize = size_bad_cov/(1-breadth_thresh)  # our initial window size.

    # get end position of alignment based on cigar
    # sam_output = StringIO.StringIO()
    # # TODO:  how to pipe line by line to stringio from samtools?????
    # subprocess.check_call(['samtools', 'view', sorted_bam_filename], stdout=sam_output, shell=False)



    # keep track of positions with indels
    with open(depth_filename, 'r') as depth_fh:
        lastref = ""
        last_window_end = 0
        windowsize = 0
        total_window_cov = 0
        for line in depth_fh:
            ref, pos, depth = line.rstrip().split()  # pos is 1-based

            # we slid past the last ref
            if not ref == lastref and lastref:
                ave_window_cov = float(total_window_cov) / (windowsize + 1)

                # insufficient coverage over the entire last ref
                if ave_window_cov < depth_thresh:
                    raise Exception("Reference " + lastref + " average coverage of " + ave_window_cov +
                                    " does not meet the minimum coverage threshold of " + depth_thresh)
                windowsize = 0
                total_window_cov = 0
                last_window_end = 0
                lastref = ""

            # continue sliding along current ref
            windowsize = int(pos) - last_window_end
            total_window_cov += int(depth)
            ave_window_cov = float(total_window_cov) / windowsize

            if ave_window_cov < depth_thresh:  # extend window
                best_size = max(best_size, windowsize)
            else:  # window has sufficient coverage.  Start another window.
                windowsize = 0
                total_window_cov = 0
                last_window_end = int(pos)

            lastref = ref

        return best_size  # NOPE!  check out http://seqanswers.com/forums/showthread.php?t=25587 ?


def get_seq_dnds_info(dnds_tsv_dir, pvalue_thresh, ref, ref_codon_len):
    """
    For an entire window, get the average dn/ds for every base position.
    We expect that all HyPhy has written out dn/ds tsv files for every window.

    :rtype SeqDnDsInfo object
    :param dnds_tsv_dir: 
    :param pvalue_thresh:
    :param str ref: reference contig/chromosome name.  Does not include the '>' faster header delimter or
                    any thing after the first space in the header text
    :param int ref_codon_len:  length of the reference in codons

    Assumes these are the columns in the HyPhy DN/DS TSV output:
    - Observed S Changes
    - Observed NS Changes
    - E[S Sites]: proportion of random one-nucleotide substitutions that are expected to be synonymous
    - E[NS Sites]: proportion of random one-nucleotide substitutions that are expected to be non-synonymous
    - Observed S. Prop.: observed proportion of synomymous substitutions = Observed S Changes / (Observed S Changes + Observed NS Changes)
    - P{S}:  proportion of substitutions expected to be synonymous under neutral evolution = E[S Sites]/(E[S Sites] + E[NS Sites])
    - dS: observed synonymous substitutions / expected proportion synonymous substitutions = Observed S Changes / E[S Sites]
    - dN: observed non synonymous substitutions / expected proportion nonsynonymous substitutions = Observed NS Changes / E[NS Sites]
    - dN-dS:  difference between dS and dN
    - P{S leq. observed}:  binomial distro pvalue.  Probability of getting less than the observed synynomous substitutions
        under the binomial distribution where probability of 1 synonymous codon = P{S}
    - P{S geq. observed}: binomial distro  pvalue (for the other tail).  Probability of getting more than the observed synynomous substitutions
        under the binomial distribution where probability of 1 synonymous codon = P{S}
    - Scaled dN-dS:  dN-dS normalized by the total length of the tree.

    We only want significant Dn/Ds.  Use the normalized value so that dn/ds can be compared from every window.
    """
    seq_dnds_info = SeqDnDsInfo(seq_len=ref_codon_len)

    for dnds_tsv_filename in glob.glob(dnds_tsv_dir + os.sep + "*.dnds.tsv"):
        with open(dnds_tsv_filename, 'r') as dnds_fh:
            # *.{start bp}_{end bp}.dnds.tsv filenames use 1-based nucleotide position numbering
            dnds_tsv_fileprefix = dnds_tsv_filename.split('.dnds.tsv')[0]
            win_nuc_range = dnds_tsv_fileprefix.split('.')[-1]
            # Window ends at this 1-based nucleotide position with respect to the reference
            win_start_nuc_pos_1based_wrt_ref = int(win_nuc_range.split('_')[0])
            # Window starts at this 1-based codon position with respect to the reference
            win_start_codon_1based_wrt_ref = win_start_nuc_pos_1based_wrt_ref/NUC_PER_CODON + 1

            msa_slice_fasta_filename = dnds_tsv_fileprefix + ".fasta"
            codons_by_window_pos = Utility.get_total_codons_by_pos(msa_fasta_filename=msa_slice_fasta_filename)

            reader = csv.DictReader(dnds_fh, delimiter='\t',)
            for offset, codon_row in enumerate(reader):    # Every codon site is a row in the *.dnds.tsv file
                pval = float(codon_row[HYPHY_TSV_PROB_FULLSEQ_S_COL])
                neg_tail_pval = float(codon_row[HYPHY_TSV_NEG_PROB_FULLSEQ_S_COL])
                if pval <= pvalue_thresh or neg_tail_pval <= pvalue_thresh:
                    dN = float(codon_row[HYPHY_TSV_DN_COL])
                    dS = float(codon_row[HYPHY_TSV_DS_COL])
                    dn_minus_ds = float(codon_row[HYPHY_TSV_SCALED_DN_MINUS_DS_COL])
                    syn_subs = float(codon_row[HYPHY_TSV_S_COL])
                    nonsyn_subs = float(codon_row[HYPHY_TSV_N_COL])

                    ref_codon_1based = win_start_codon_1based_wrt_ref + offset
                    codons = codons_by_window_pos[offset]

                    if dS == 0:
                        dnds = None
                    else:
                        dnds = dN/dS
                    seq_dnds_info.add_site_dnds(site_1based=ref_codon_1based, dnds=dnds, dn_minus_ds=dn_minus_ds,
                                                reads=codons, syn_subs=syn_subs, nonsyn_subs=nonsyn_subs)

    return seq_dnds_info



def tabulate_dnds(dnds_tsv_dir, ref, ref_nuc_len, pvalue_thresh, output_dnds_tsv_filename, comments):
    seq_dnds_info = get_seq_dnds_info(dnds_tsv_dir=dnds_tsv_dir, pvalue_thresh=pvalue_thresh, ref=ref,
                                                    ref_codon_len=ref_nuc_len/NUC_PER_CODON)
    with open(output_dnds_tsv_filename, 'w') as dnds_fh:
        dnds_fh.write("# " + comments + "\n")
        dnds_fh.write("Ref\tSite\tdNdS\tdN_minus_dS\tWindows\tCodons\tNonSyn\tSyn\tSubst\n")
        for site in range(1, seq_dnds_info.get_seq_len() + 1):
            site_dnds = seq_dnds_info.get_site_ave_dnds(site_1based=site)
            site_dn_minus_ds = seq_dnds_info.get_site_ave_dn_minus_ds(site_1based=site)
            window = seq_dnds_info.get_site_window_cov(site_1based=site)
            reads = seq_dnds_info.get_site_ave_read_cov(site_1based=site)
            nonsyn = seq_dnds_info.get_site_ave_nonsyn_subs(site_1based=site)
            syn = seq_dnds_info.get_site_ave_syn_subs(site_1based=site)
            subs = seq_dnds_info.get_site_ave_subs(site_1based=site)

            line = "\t".join((ref, str(site), str(site_dnds), str(site_dn_minus_ds), str(window), str(reads),  str(nonsyn), str(syn), str(subs)))
            dnds_fh.write(line + "\n")
    return seq_dnds_info