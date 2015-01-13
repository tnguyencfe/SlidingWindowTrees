#!/usr/bin/python
"""
Batch INDELible
Write control.txt file and execute indelible to simulate sequences.
"""

import sys
import os
import csv
import subprocess
import csv

INDELIBLE_SITE_INFO_START = 8  # The line that the site information actually starts on.  Line is 0-based. Sites are 1-based
RANDOM_SEED = 10


# dN/dS values following a discrete gamma distro
# Gamma(shape=1.5, rate=3), histogram with 50 breaks
OMEGAS = [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.05, 1.15, 1.25, 1.35, 1.45, 1.55, 1.65,
        1.75, 1.85, 1.95, 2.05, 2.15, 2.25, 2.35, 2.45, 2.55, 2.65, 2.75, 2.85, 2.95, 3.05, 3.15, 3.25, 3.35,
        3.45, 3.55, 3.65, 3.75, 3.85, 3.95, 4.05, 4.15, 4.25, 4.35, 4.45, 4.55, 4.65, 4.75, 4.85, 4.95, 5.05,
        5.15, 5.25, 5.35, 5.45, 5.55, 5.65, 5.75, 5.85, 5.95, 6.05]

# Probabilities of each discrete gamma distro category in OMEGAS
PROP = [0.1038610, 0.1432928, 0.1381003, 0.1212857, 0.1020363, 0.0835798, 0.0673901, 0.0535906,
        0.0422005, 0.0329969, 0.0258732, 0.0200207, 0.0154661, 0.0118681, 0.0090903, 0.0070075,
        0.0053782, 0.0040914, 0.0031212, 0.0023785, 0.0017896, 0.0013684, 0.0010189, 0.0007866,
        0.0005856, 0.0004496, 0.0003366, 0.0002510, 0.0001857, 0.0001455, 0.0001097, 0.0000839,
        0.0000653, 0.0000442, 0.0000391, 0.0000294, 0.0000200, 0.0000160, 0.0000124, 0.0000084,
        0.0000066, 0.0000052, 0.0000031, 0.0000022, 0.0000017, 0.0000016, 0.0000009, 0.0000008,
        0.0000008, 0.0000003, 0.0000002, 0.0000002, 0.0000002, 0.0000001, 0.0000003, 0.0000001,
        0.0000002, 0.0000001, 0.0000001, 0.0000001, 0.0000001]

KAPPA = 8.0  # Transition/Transversion ratio


treefile = sys.argv[1]
intervals_csv = sys.argv[2]
seed = sys.argv[3]


handle = open(treefile, 'rU')
tree_string = handle.readline()
handle.close()

num_codon_sites = 0


# There can be multiple intervals for the same scaling factor
# Number of codon sites will be the sum of all codons for all intervals
with open(intervals_csv, 'rU') as fh_intervals:  #scaling_factor,num_codons,outdir,out_filename_prefix
    reader = csv.DictReader(fh_intervals)
    for interval_row in reader:
        num_codon_sites += int(interval_row["num_codons"])

done_files = []
with open(intervals_csv, 'rU') as fh_intervals:  #scaling_factor,num_codons,outdir,out_filename_prefix
    reader = csv.DictReader(fh_intervals)

    for interval_row in reader:
        output_dir = interval_row["outdir"]
        output_filename_prefix = interval_row["out_filename_prefix"]
        if output_dir + output_filename_prefix in done_files:
            continue
        done_files.extend([output_dir + output_filename_prefix])
        global_scaling_factor = float(interval_row["scaling_factor"])
        print "Creating indelible output for tree scaled by " + str(global_scaling_factor) + " to " + output_dir + os.sep + output_filename_prefix + str(global_scaling_factor) + "*"

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # The *.fasta files contain the unaligned sequences of the leaves (the current individuals in the population).
        # The *_TRUE.fasta files contain the aligned sequences of the leaves (the current individuals in the population).
        # The *_ANCESTORS.fasta files contain the sequences of the inner nodes (the ancestors of the population).
        output_fasta = output_dir + os.sep + "{}{}_TRUE.fasta".format(output_filename_prefix, global_scaling_factor)

        # Do not overwrite existing fastas
        if os.path.exists(output_fasta) and os.path.getsize(output_fasta) > 0:
            print(output_fasta + " already exists.  Not regenerating")
        else:
            # Write the control.txt file into the output directory.
            # Set the working directory of indelible to that output dir so that we can run indelible without clobbering previous results
            with open(output_dir + os.sep + 'control.txt', 'w') as handle:
                # write minimal contents of INDELible control file
                handle.write('[TYPE] CODON 1\n')
                handle.write('[SETTINGS]\n')
                handle.write('[ancestralprint] NEW\n')  # output ancestral sequences in separate file
                handle.write('[output] FASTA\n') # NB:  indelible nexus file only contains the alignment not the tree.  Might as well use fasta since more common format.
                handle.write('[fastaextension] fasta\n')
                handle.write('[printrates] TRUE\n')
                handle.write('[randomseed] ' + str(RANDOM_SEED) + '\n')
                handle.write('[MODEL] M3\n[submodel] %f\n' % KAPPA)

                prop_string = ''
                omega_string = ''
                for i, omega in enumerate(OMEGAS):
                    if i < (len(OMEGAS)-1):
                        prop_string += ' %f' % PROP[i]
                    omega_string += ' %1.2f' % omega

                handle.write(prop_string + '\n')
                handle.write(omega_string + '\n')

                #handle.write('[TREE] bigtree %s;\n' % tree_string.rstrip('0123456789.;:\n'))
                handle.write('[TREE] bigtree %s\n' % tree_string)
                handle.write('[treelength] %1.1f\n' % global_scaling_factor)
                handle.write('[PARTITIONS] partitionname\n')
                handle.write('  [bigtree M3 %d]\n' % num_codon_sites)
                handle.write('[EVOLVE] partitionname 1 %s%1.1f\n' % (output_filename_prefix, global_scaling_factor))


            subprocess.check_call(["indelible"], env=os.environ, cwd=output_dir)




        # Copy the contents of the scaling_<mutation scaling rate>_RATES.txt autogenerated by indelible
        # and append the site dN/dS  (omega) values.
        # Indelible does not output these by default since it allows for different dN/dS per branch
        # (although only 1 dN/dS class per site)

        # The *_RATES.txt file are autogenerated by indelible and contain Site --> discrete omega category mappings
        output_rates_txt = output_dir + os.sep + "{}{}_RATES.txt".format(output_filename_prefix, global_scaling_factor)
        # The *_RATES.csv file are autogenerated by us and contain Site --> omega mappings
        output_rates_csv = output_dir + os.sep + "{}{}_RATES.csv".format(output_filename_prefix, global_scaling_factor)

        # Do not overwrite existing rates files
        if (os.path.exists(output_rates_csv) and os.path.getsize(output_rates_csv) > 0 and
                    os.path.getmtime(output_rates_csv) >= os.path.getmtime(output_fasta)):
            print(output_rates_csv + " already exists.  Not regenerating")
        else:
            with open(output_rates_txt, 'rU') as fh_in, open(output_rates_csv, 'w') as fh_out:
                for line_ctr, line in enumerate(fh_in):
                    if line_ctr >= INDELIBLE_SITE_INFO_START:
                        break

                reader = csv.DictReader(fh_in, delimiter="\t")
                writer = csv.DictWriter(fh_out, fieldnames=reader.fieldnames + ["Omega"])
                writer.writeheader()
                for row in reader:
                    # Cols: Site	Class	Partition	Inserted?
                    site_class = int(row["Class"])  # classes are 0-based numbers.  The discrete category corresponding to the OMEGA value.
                    site_omega = OMEGAS[site_class]
                    outrow = row
                    outrow["Omega"] = site_omega
                    writer.writerow(outrow)

                # Delete original rates file autogenerated by indelible
                #os.remove(output_rates_txt)