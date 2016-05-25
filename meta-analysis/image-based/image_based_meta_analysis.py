"""
Perform a simple meta-analysis (as the third level of a hierarchical GLM)
based on a set of NIDM-Results exports.

@author: Camille Maumet <c.m.j.maumet@warwick.ac.uk>
@copyright: University of Warwick 2015
"""
import os
from rdflib.graph import Graph
from rdflib.term import URIRef
from subprocess import check_call
from nidmresults.objects.constants import SCR_FSL, SCR_SPM
import collections
import glob
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
data_dir = os.path.join(SCRIPT_DIR, "..", "..", "data", "pain")
print data_dir
assert os.path.isdir(data_dir)

pre_dir = os.path.join(SCRIPT_DIR, "data")
FSL_DESIGN_DIR = os.path.join(SCRIPT_DIR, "fsl_design")

if not os.path.exists(pre_dir):
    os.makedirs(pre_dir)

studies = glob.glob(os.path.join(data_dir, '*.nidm.zip'))

con_maps = dict()
varcon_maps = dict()
mask_maps = dict()

ma_mask_name = os.path.join(pre_dir, "meta_analysis_mask")
ma_mask = None

# studies = studies[0:3]

for nidm_file in studies:
    nidm_dir = nidm_file.replace(".nidm.zip", "")
    study = os.path.basename(nidm_dir)
    print "\nStudy: " + study

    with zipfile.ZipFile(nidm_file) as z:
        if not os.path.exists(nidm_dir):
            os.makedirs(nidm_dir)
        z.extractall(nidm_dir)

    nidm_doc = os.path.join(nidm_dir, "nidm.ttl")
    assert os.path.isfile(nidm_doc)

    nidm_graph = Graph()
    nidm_graph.parse(nidm_doc, format='turtle')

    query = """
    prefix prov: <http://www.w3.org/ns/prov#>
    prefix nidm: <http://purl.org/nidash/nidm#>

    prefix contrast_estimation: <http://purl.org/nidash/nidm#NIDM_0000001>
    prefix contrast_map: <http://purl.org/nidash/nidm#NIDM_0000002>
    prefix stderr_map: <http://purl.org/nidash/nidm#NIDM_0000013>
    prefix contrast_name: <http://purl.org/nidash/nidm#NIDM_0000085>
    prefix statistic_map: <http://purl.org/nidash/nidm#NIDM_0000076>
    prefix mask_map: <http://purl.org/nidash/nidm#NIDM_0000054>

    SELECT ?contrastName ?con_file ?std_file
    ?mask_file ?software WHERE {
     ?con_id a contrast_map: ;
          contrast_name: ?contrastName ;
          prov:atLocation ?con_file ;
          prov:wasGeneratedBy ?con_est .
     ?std_id a stderr_map: ;
          prov:atLocation ?std_file ;
          prov:wasGeneratedBy ?con_est .
     ?mask_id a mask_map: ;
          prov:atLocation ?mask_file .
     ?soft_id a ?software .
     ?con_est a contrast_estimation: ;
              prov:wasAssociatedWith ?soft_id ;
              prov:used ?mask_id .

      FILTER(?software NOT IN (
        prov:SoftwareAgent, prov:Agent))
    }

    """
    sd = nidm_graph.query(query)

    if sd:
        for row in sd:
            con_name, con_file, std_file, mask_file, software = row
            con_file = os.path.join(nidm_dir, con_file)
            std_file = os.path.join(nidm_dir, std_file)
            mask_file = os.path.join(nidm_dir, mask_file)

            if str(con_name) == "pain":
                if software == URIRef(SCR_SPM.uri):
                    print "--> analyzed with SPM"
                    # If study was performed with SPM, reslice to FSL's
                    # template space
                    for to_reslice in [con_file, std_file, mask_file]:
                        file_name = os.path.basename(to_reslice).split(".")[0]
                        resliced_file = os.path.join(
                            pre_dir, study + "_" + file_name + "_r")
                        cmd = [
                            "cd \"" + nidm_dir + "\";" +
                            " flirt -in " + file_name + " -ref " +
                            "$FSLDIR/data/standard/MNI152_T1_2mm -applyxfm " +
                            "-usesqform " +
                            "-out " + resliced_file
                            ]
                        print "Running " + ",".join(cmd)
                        check_call(cmd, shell=True)

                        if to_reslice == mask_file:
                            mask_file = resliced_file
                        elif to_reslice == con_file:
                            con_maps[study] = resliced_file
                        elif to_reslice == std_file:
                            std_file = resliced_file

                elif software == URIRef(SCR_FSL.uri):
                    print "--> analyzed with FSL"
                    # If study was performed with FSL, rescale to a target
                    # value of 100
                    for to_rescale in [con_file, std_file]:
                        file_name = os.path.basename(to_rescale).split(".")[0]
                        rescaled_file = os.path.join(
                            pre_dir, study + "_" + file_name + "_s")
                        cmd = [
                            "cd \"" + nidm_dir + "\";" +
                            " fslmaths \"" + file_name + "\" -div 100 " +
                            " \"" + rescaled_file + "\""
                            ]
                        print "Running " + ",".join(cmd)
                        check_call(cmd, shell=True)

                        if to_rescale == con_file:
                            con_maps[study] = "\"" + rescaled_file + "\""
                        elif to_rescale == std_file:
                            std_file = "\"" + rescaled_file + "\""

                    mask_file = mask_file.replace("file://.", nidm_dir)

                else:
                    raise Exception(
                        'Unknown neuroimaging software: ' + str(software))

                # Create varcope from standard error map
                varcope_file = "\"" + \
                               os.path.join(pre_dir, study + "_varcope") + \
                               "\""
                cmd = [" fslmaths " + std_file + " -sqr " + varcope_file]
                print "Running " + ",".join(cmd)
                check_call(cmd, shell=True)

                varcon_maps[study] = varcope_file

                # Compute meta-analysis mask as the intersection of all
                # study analysis masks
                if ma_mask is None:
                    ma_mask = mask_file
                else:
                    cmd = [
                        " fslmaths \"" + mask_file + "\" -min " +
                        "\"" + ma_mask + "\" \"" + ma_mask_name + "\""
                        ]
                    print "Running " + ",".join(cmd)
                    check_call(cmd, shell=True)
                    ma_mask = ma_mask_name
            else:
                print "Ignore contrast '" + str(con_name) + "'."

    else:
        print "Query returned no results for study "+study+"."

# Binarize the analysis mask
cmd = ["fslmaths \"" + ma_mask + "\" -thr 0.9 -bin \"" + ma_mask + "\""]
print "Running " + ",".join(cmd)
check_call(cmd, shell=True)

# Sort copes and varcopes by study names
to_merge = {'copes': collections.OrderedDict(sorted(con_maps.items())),
            'varcopes': collections.OrderedDict(sorted(varcon_maps.items()))}
for file_name, files in to_merge.items():
    cmd = [
        "fslmerge -t \""+os.path.join(pre_dir, file_name) +
        ".nii.gz\" "+" ".join(files.values())
    ]
    print "Running " + ",".join(cmd)
    check_call(cmd, shell=True)

cmd = [
    "cd " + pre_dir + "; flameo --cope=copes --vc=varcopes --ld=stats "
    " --dm=" + os.path.join(FSL_DESIGN_DIR, "simple_meta_analysis.mat") +
    " --cs=" + os.path.join(FSL_DESIGN_DIR, "simple_meta_analysis.grp") +
    " --tc=" + os.path.join(FSL_DESIGN_DIR, "simple_meta_analysis.con ") +
    " --mask=\""+ma_mask_name+"\" --runmode=flame1"]
print "Running " + ",".join(cmd)
check_call(cmd, shell=True)

stat_dir = os.path.join(pre_dir, "stats")

# # Uncorrected p-value from z-statistic
# cmd = ["cd " + stat_dir + ";" + "fslmaths zstat1 -ztop punc"]
# print "Running " + ",".join(cmd)
# check_call(cmd, shell=True)

# # FDR-adjusted p-values from uncorrected p-values
# cmd = ["cd " + stat_dir + ";" + "fdr -i punc -q 0.05 -a pfdr -m mask"]
# print "Running " + ",".join(cmd)
# check_call(cmd, shell=True)

# # Excursion set (pFDR<0.05) filled with 1 - (FDR-adjusted p-values < 0.05)
# cmd = [
#     "cd " + stat_dir + ";" +
#     "fslmaths pfdr -mul -1 -add 1 -thr 0.95 -mas mask invpfdr_fdr05"
#     ]
# print "Running " + ",".join(cmd)
# check_call(cmd, shell=True)

# # Excursion set filled with zstat
# cmd = [
#     "cd " + stat_dir + ";" +
#     "fslmaths zstat1 -mas invpfdr_fdr05 zstat1_fdr05"
#     ]
# print "Running " + ",".join(cmd)
# check_call(cmd, shell=True)

# # logn(unc. p-values) from cope, varcope and dof
# cmd = ["cd " + stat_dir + ";" + "ttologp -logpout logp1 varcope1 cope1 20"]
# print "Running " + ",".join(cmd)
# check_call(cmd, shell=True)

# # Excursion set filled with -log10(unc. p-values) from logn(unc. p-values)
# # note: log10(p-values) = log(p-values)/2.3026
# cmd = [
#     "cd " + stat_dir + ";" +
#     "fslmaths logp1.nii.gz -div -2.3026 " +
#     "-mas zstat1_fdr05 mlog10p_fdr05"
# ]
# print "Running " + ",".join(cmd)
# check_call(cmd, shell=True)
