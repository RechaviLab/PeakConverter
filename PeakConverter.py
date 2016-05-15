from collections import deque
from signal import signal, SIGPIPE, SIG_DFL
import subprocess
import tempfile
import sys
import pandas as pd

"""
This program receives the RefSeq UCSC table file and a cufflinks isoform FPKM
file as input and outputs a bed file with transcriptomic coordinates, a bed file
with genomic coordinates limited to exons and an excel file for metagene analysis.
WORKS WITH THE FOLLOWING ANNOTATIONS:
RefSeq, Ensemble and GENCODE.
DOES NOT WORK WITH UCSC ANNOTATION.
"""


class Transcript:
    def __init__(self, tx_id, chrom, strand, tx_start, tx_end, cds_start,
                 cds_end, exon_starts, exon_ends, gene_id, uid):
        self.id = tx_id   # Transcript ID
        self.uid = uid   # Unique ID in case of duplicate transcript IDs
        self.chrom = chrom   # Chromosome of transcript
        self.strand = strand
        self.txs = tx_start   # Transcription start site
        self.txe = tx_end   # Transcription end site
        self.cdss = cds_start   # CDS start site
        self.cdse = cds_end   # CDS end site
        self.genomic_starts = exon_starts   # List of exon starting points
        self.genomic_ends = exon_ends   # List of exon ending points
        self.gid = gene_id   # Gene ID
        self.trans_starts = deque()   # Deque of exon starting points in transcriptomic coords
        self.trans_ends = deque()   # Deque of exon ending points in transcriptomic coords
        self.type = None   # Coding or non-coding transcript
        self.ctis = None   # Transcriptomic location of canonical ATG
        self.stop = None   # Transcriptomic location of stop codon
        self.get_transcriptomic_coordinates()
        self.get_start_stop()

    def __len__(self):
        return sorted(self.trans_ends, reverse=True)[0]

    def get_transcriptomic_coordinates(self):
        """
        This class function calculates the transcriptomic coordinates of each exon
        in the transcript from their genomic coordinates.
        """
        if self.strand == "+":
            b = 0
            for index, exon_st in enumerate(self.genomic_starts):
                exon_end = self.genomic_ends[index]
                tr_exon_st = b
                tr_exon_end = b + exon_end - exon_st
                self.trans_starts.append(tr_exon_st)
                self.trans_ends.append(tr_exon_end)
                b = b + exon_end - exon_st
        elif self.strand == "-":
            b = 0
            for index, exon_st in enumerate(reversed(self.genomic_starts)):
                exon_end = list(reversed(self.genomic_ends))[index]
                tr_exon_st = b
                tr_exon_end = b + exon_end - exon_st
                self.trans_starts.appendleft(tr_exon_st)
                self.trans_ends.appendleft(tr_exon_end)
                b = b + exon_end - exon_st

    def get_start_stop(self):
        """
        This class function calculates the transcriptomic coordinates of the canonical
        start codon and the stop codon. It returns -1 for both if it is a non-coding
        transcript.
        """
        if self.cdss == self.cdse:
            self.ctis = -1
            self.stop = -1
            self.type = "non-coding"
        else:
            self.type = "coding"
            for exon_start, exon_end, tr_exon_start in zip(self.genomic_starts, self.genomic_ends,
                                                           self.trans_starts):
                if exon_start <= self.cdss <= exon_end:
                    if self.strand == "+":
                        self.ctis = tr_exon_start + self.cdss - exon_start
                    else:
                        self.stop = tr_exon_start + exon_end - self.cdss
                if exon_start <= self.cdse <= exon_end:
                    if self.strand == "+":
                        self.stop = tr_exon_start + self.cdse - exon_start
                    else:
                        self.ctis = tr_exon_start + exon_end - self.cdse


def build_transcript(array_line):
    """
    This function takes a line from the table array (which is a list) and uses
    the class Transcript to build a transcript from that line. It outputs the
    transcript object.
    """
    uid = array_line[0]
    tx_id = array_line[1]
    chrom = array_line[2]
    strand = array_line[3]
    txStart = array_line[4]
    txEnd = array_line[5]
    cdsStart = array_line[6]
    cdsEnd = array_line[7]
    exonStarts_list = array_line[8]
    exonEnds_list = array_line[9]
    gene_id = array_line[10]
    return Transcript(tx_id, chrom, strand, txStart, txEnd, cdsStart,
                      cdsEnd, exonStarts_list, exonEnds_list, gene_id, uid)


def build_transcriptome(table_array, key='uid'):
    """
    This function takes a table array generated by read_table_into_array and a key
    and returns a dictionary in which the values are lists of objects of the class
    Transcript.
    """
    transcripts = {}
    keydict = {'uid': 0, 'gid': 10, 'txid': 1}
    if key not in ['gid', 'txid', 'uid']:
        print('Invalid key type for transcripts dictionary! Aborting.')
        sys.exit(0)
    else:
        for line in table_array:
            if line[keydict[key]] not in transcripts:   # Check if key already exists in dictionary
                transcripts[line[keydict[key]]] = [build_transcript(line)]
            else:
                transcripts[line[keydict[key]]].append(build_transcript(line))
    return transcripts


def get_parameters(tx_dict):
    """
    This function takes a transcript dictionary and returns a pandas
    dataframe of the parameters Tx_ID, ATG, Stop, Length, First Splice Site, Last Splice Site and UID.
    This dataframe will later be used to add these paramters to transcripts for which peaks were
    mapped to.
    UID is best used due to duplicate transcript IDs in some annotations.
    :param tx_dict: Transcript dictionary
    :return: parameters_df: Dataframe of parameters
    """
    parameters = []
    parameter_list = ['Tx_ID', 'ATG', 'Stop', 'Length', 'FirstSpliceSite', 'LastSpliceSite', 'UID']
    for tx_class in tx_dict:
        for tx in tx_dict[tx_class]:
            if len(tx.chrom)<=5:
                starts = sorted(tx.trans_starts)
                if len(starts) > 1 and tx.ctis > 0:   # Check if transcript is spliced and coding
                    par = {'Tx_ID': tx.id,
                           'ATG': tx.ctis,
                           'Stop': tx.stop,
                           'Length': len(tx),
                           'FirstSpliceSite': starts[1],
                           'LastSpliceSite': starts[-1],
                           'UID': tx.uid}
                elif len(starts) > 1:   # Transcript is spliced but not coding
                    par = {'Tx_ID': tx.id,
                           'ATG': '-1',
                           'Stop': '-1',
                           'Length': len(tx),
                           'FirstSpliceSite': starts[1],
                           'LastSpliceSite': starts[-1],
                           'UID': tx.uid}
                elif tx.ctis > 0:   # Transcript is coding but not spliced
                    par = {'Tx_ID': tx.id,
                           'ATG': tx.ctis,
                           'Stop': tx.stop,
                           'Length': len(tx),
                           'FirstSpliceSite': '-1',
                           'LastSpliceSite': '-1',
                           'UID': tx.uid}
                else:   # Transcript is non-coding and not spliced
                    par = {'Tx_ID': tx.id,
                           'ATG': '-1',
                           'Stop': '-1',
                           'Length': len(tx),
                           'FirstSpliceSite': '-1',
                           'LastSpliceSite': '-1',
                           'UID': tx.uid}
                parameters.append([par[parm] for parm in parameter_list])
    parameters_df = pd.DataFrame(parameters)
    parameters_df.columns = [parm for parm in parameter_list]
    return parameters_df


def gen2tr(bedfile, tx_dict):
    """
    This function takes a genomic bed file and a dictionary of transcripts (of class Transcript),
    intersects the bed file with the transcripts using bedtools intersect and outputs the
    transcriptomic coordinates of the bed features into a file name of choice
    """
    print("---Building temporary conversion BED file...", end=" ")
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_bed_key:
        for tx_class in tx_dict:
            if len(tx_dict[tx_class]) == 1:  # Check that this is an isoform without duplicates
                for tx in tx_dict[tx_class]:
                    for exon_start, exon_end, tr_exon_st, tr_exon_end in \
                        zip(tx.genomic_starts, tx.genomic_ends,
                            tx.trans_starts, tx.trans_ends):
                        print(tx.chrom, exon_start, exon_end, "*", "*",
                              tx.strand, tx.uid, tr_exon_st, tr_exon_end,
                              sep="\t", file=temp_bed_key)
        temp_bed_key.seek(0)
        print("Done!")
        print("---Intersecting BED files...", end=" ")
        intersection = subprocess.Popen(['bedtools', 'intersect', '-a',
                                         bedfile, '-b', temp_bed_key.name,
                                         '-wo'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        exon_limited_peaks = subprocess.Popen(['bedtools', 'intersect', '-a',
                                               bedfile, '-b', temp_bed_key.name,
                                               '-f', '0.5'], stdout=subprocess.PIPE)
        print("Done!")
        print("---Sorting, merging and outputting exon-limited peaks to file...", end=" ")
        sorted_elp = subprocess.Popen(['bedtools', 'sort', '-i'],
                                      stdin=exon_limited_peaks.stdout,
                                      stdout=subprocess.PIPE)
        merged_elp = subprocess.Popen(['bedtools', 'merge', '-nms', '-i'],
                                      stdin=sorted_elp.stdout,
                                      stdout=subprocess.PIPE)
        with open(args.output+'_exonpeaks.bed', 'w') as exon_peak_output:
            for l in merged_elp.stdout:
                print(l.decode().strip(), file=exon_peak_output)
        print("Done!")
#    a = pd.read_csv(intersection.stdout, header=None, sep='\t')
#    a.to_csv('intersection.log', sep='\t', header=False, index=False)
    print("---Creating transcriptomic coordinates output...", end=" ")
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_tr_bed:
        for line in intersection.stdout:
            myline = line.decode().strip().split()
            p_start = int(myline[1])
            p_end = int(myline[2])
            peak_id = myline[3]
            ex_st = int(myline[-9])
            ex_end = int(myline[-8])
            strand = myline[-5]
            uid = myline[-4]
            tr_exon_start = int(myline[-3])
            overlap = int(myline[-1])
            if strand == "+":
                if p_start <= ex_st:
                    print(uid, tr_exon_start, tr_exon_start+overlap, peak_id,
                          sep="\t", file=temp_tr_bed)
                elif p_start > ex_st:
                    gap = p_start - ex_st
                    print(uid, tr_exon_start+gap, tr_exon_start+gap+overlap, peak_id,
                          sep="\t", file=temp_tr_bed)
            elif strand == "-":
                if p_end >= ex_end:
                    print(uid, tr_exon_start, tr_exon_start+overlap, peak_id,
                          sep="\t", file=temp_tr_bed)
                elif p_end < ex_end:
                    gap = ex_end - p_end
                    print(uid, tr_exon_start+gap, tr_exon_start+gap+overlap, peak_id,
                          sep="\t", file=temp_tr_bed)
        temp_tr_bed.seek(0)
        sorted_bed = subprocess.Popen(['bedtools', 'sort', '-i', temp_tr_bed.name],
                                      stdout=subprocess.PIPE)
        merged_bed = subprocess.Popen(['bedtools', 'merge', '-nms', '-d', '10', '-i'],
                                      stdin=sorted_bed.stdout, stdout=subprocess.PIPE)
        trdf = pd.read_csv(merged_bed.stdout, header=None, sep='\t')
        trdf.columns = ['UID', 'Peak_Start', 'Peak_End', 'Peak_Names']
        print("Done!")
        return trdf


def get_user_arguments():
    """
    This function parses the user supplied arguments using argparse.
    It returns a parser.parse_args object.
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--bed-file', action='store', dest='bedfile', required=True,
                        help='Path to MACS2 Peaks file (Or other BED format peak file)')
    parser.add_argument('--table-file', action='store', dest='tablefile', required=True,
                        help='Path to Annotation Table file')
    parser.add_argument('--output-prefix', action='store', dest='output', required=True,
                        help='Prefix of output files')
    parser.add_argument('--expression-file', action='store', dest='expfile', required=True,
                        help='Path to cufflinks output isoforms.fpkm_tracking file')
    return parser.parse_args()


def read_table_into_array(table_file, selected_transcripts=None):
    """
    This function takes a table file and a set of transcripts and
    loads the selected transcripts into an array (list of lists). If no list
    of transcripts is supplied then it loads all transcripts into the array.
    The array has the following columns:
    UID|Tx ID|Chrom|Strand|Tx Start|Tx End|CDS Start|CDS End|Exon Starts (List)|
    Exon Ends (List)|Gene ID
    """
    with open(table_file, 'r') as opened_table_file:
        first_line = opened_table_file.readline().strip().split()
        id_counter = 1
        table_array = []
        if selected_transcripts:
            if "bin" in first_line[0]:
                for line in opened_table_file:
                    split_line = line.strip().split('\t')[1:]
                    if split_line[0] in selected_transcripts:
                        integer_values = [int(split_line[a]) for a in range(3, 7)]
                        exon_starts = [int(a) for a in split_line[8].split(',')[:-1]]
                        exon_ends = [int(a) for a in split_line[9].split(',')[:-1]]
                        table_array.append([id_counter] + split_line[:3] + integer_values +
                                           [exon_starts] + [exon_ends] + [split_line[11]])
                        id_counter += 1
            else:
                print("The table file is not at the right format.")
                print("Please remember only RefSeq/GENCODE/Ensemble annotations are supported.")
                sys.exit(0)
        else:
            if "bin" in first_line[0]:
                for line in opened_table_file:
                    split_line = line.strip().split('\t')[1:]
                    integer_values = [int(split_line[a]) for a in range(3, 7)]
                    exon_starts = [int(a) for a in split_line[8].split(',')[:-1]]
                    exon_ends = [int(a) for a in split_line[9].split(',')[:-1]]
                    table_array.append([id_counter] + split_line[:3] + integer_values +
                                       [exon_starts] + [exon_ends] + [split_line[11]])
                    id_counter += 1
            else:
                print("The table file is not at the right format.")
                print("Please remember only RefSeq/GENCODE/Ensemble annotations are supported.")
                sys.exit(0)
    return table_array


def isoform_gene_dict(table_file):
    """
    This function receives a table file and returns a dictionary in which
    the keys are isoforms and the values are genes and coding info, for use in the
    choose_selected_cufflinks function.
    """
    with open(table_file, 'r') as opened_table_file:
        first_line = opened_table_file.readline().strip().split()
        gene_dict = {}
        if "bin" in first_line[0]:
            for line in opened_table_file:
                split_line = line.strip().split('\t')[1:]
                if split_line[7] == split_line[6]:
                    gene_dict[split_line[0]] = (split_line[11], 0)
                else:
                    gene_dict[split_line[0]] = (split_line[11], 1)
        else:
            print("The table file is not at the right format.")
            print("Please remember only RefSeq/GENCODE/Ensemble annotations are supported.")
            sys.exit(0)
    return gene_dict


def choose_selected_cufflinks(input_file, table_file):
    """
    This function receives a cufflinks output file isoforms.fpkm_tracking
    and a UCSC table file.
    It chooses the isoforms that will be used for genomic to transcriptomic
    conversion in the following order:
    1. Most expressed isoform of a gene by FPKM
    2. Longest coding isoform.
    3. Longest isoform.
    It returns a set of the chosen isoforms.
    """
    iso_dict = {}
    ret_list = []
    c = 0
    gene_dict = isoform_gene_dict(table_file)
    with open(input_file, 'r') as input_f:
        _ = input_f.readline()
        for line in input_f:
            fline = line.strip().split()
            isoform = fline[3]
            fpkm = float(fline[9])
            txlength = int(fline[7])
            if isoform in gene_dict:
                gene = gene_dict[isoform][0]
                coding = gene_dict[isoform][1]
                if gene in iso_dict:
                    if fpkm > iso_dict[gene][1]:
                        iso_dict[gene] = (isoform, fpkm, txlength, coding)
                    elif fpkm == iso_dict[gene][1] and coding == 1 \
                            and iso_dict[gene][3] == 0:
                        iso_dict[gene] = (isoform, fpkm, txlength, coding)
                    elif fpkm == iso_dict[gene][1] and txlength > iso_dict[gene][2]:
                        iso_dict[gene] = (isoform, fpkm, txlength, coding)
                else:
                    iso_dict[gene] = (isoform, fpkm, txlength, coding)
            else:
                print("Isoform "+str(isoform)+" was not found in table file.")
                c+=1
                if c > 5:
                    print("Over 5 isoforms not found in table file. Aborting.")
                    print("Are you sure you chose the same annotation for cufflinks and table file?")
                    sys.exit(0)
    for gene in iso_dict:
        ret_list.append(iso_dict[gene][0])
    return set(ret_list)


def check_dependencies():
    """
    This function checks that the dependencies are defined in the system's PATH.
    If not, it terminates the script.
    """
    import shutil
    if not shutil.which("bedtools"):
        print("BEDtools not installed or not defined in PATH!")
        sys.exit(0)
    return


if __name__ == "__main__":
    args = get_user_arguments()
    signal(SIGPIPE, SIG_DFL)
    print("Checking program dependencies...", end=" ")
    check_dependencies()
    print("Done!")
    print("Choosing most expressed isoform for each gene...", end=" ")
    chosen = choose_selected_cufflinks(args.expfile, args.tablefile)
    print("Done!")
    print("Loading annotation table file into array...", end=" ")
    tb_array = read_table_into_array(args.tablefile, chosen)
    print("Done!")
    print("Building transcriptome...", end=" ")
    tx_dict = build_transcriptome(tb_array, 'txid')
    print("Done!")
    print("Fetching transcriptomic parameters for metagene analysis...", end=" ")
    parameters_df = get_parameters(tx_dict)
    print("Done!")
    print("Converting genomic to transcriptomic coordinates...")
    result = gen2tr(args.bedfile, tx_dict)
    result['Peak_Middle'] = ((result['Peak_Start']+result['Peak_End'])/2)
    merged = pd.merge(result, parameters_df, on='UID')
    merged.drop_duplicates(inplace=True)
    merged = merged[['Tx_ID', 'Peak_Start', 'Peak_End', 'Peak_Names',
                     'Peak_Middle', 'ATG', 'Stop', 'Length', 'FirstSpliceSite',
                     'LastSpliceSite']]
    merged = merged[(merged.Peak_End - merged.Peak_Start) > 50]
    merged.sort_values(['Tx_ID', 'Peak_Start'], ascending=[True, True],
                       inplace=True)
    print("Done converting genomic to transcriptomic coordinates!")
    print("Writing results to file...", end=" ")
    merged.to_csv(args.output+'_tx.bed', sep='\t', header=False, index=False,
                  float_format='%.f')
    print("Done! Good luck with the analysis!")
    print("Remember, columns of tx file are:")
    print("Tx ID | Peak Start | Peak End | Peak Names | Peak Middle | ATG | "
          "Stop | Tx Length | First Splice Site | Last Splice Site")
