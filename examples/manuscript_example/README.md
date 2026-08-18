# The MYC / A549 example

Nine Artifacts built to make the specification's constructs legible, not to report a real result.

**Every measurement, study, dataset and value here is invented.** There is no MYC withdrawal study by "Okafor, C." — `lyra_pub_myc_adenocarcinoma_v1.json` is fabricated. There is no western blot or RNA-seq run — every number in `vega_data_lane_traces_v1.json`, `vega_data_myc_relative_protein_v1.json` and `vega_data_myc_rnaseq_v1.json` was made up to be internally consistent, not measured. Nothing here should be cited, imported into another record, or read as a claim about MYC, A549, or lung adenocarcinoma. The real worked record, with real published values behind every Ground, is [`../record/`](../record).

## The decision the example is built around

A laboratory is planning a genome-wide CRISPR screen for genes that modify the proliferation defect caused by MYC loss. The screen only works in a cell line that depends on MYC, and only resolves anything if the defect is partial rather than total. A549 is one candidate line. Two Arguments evaluate the same claim, the same scope, and the same three Grounds — and reach opposite verdicts, because the decision each is written for is different:

- **[`vega_arg_a549_pilot_v1.json`](vega_arg_a549_pilot_v1.json)** — whether to run a two-week pilot before committing anything. Sufficient.
- **[`vega_arg_a549_commit_v1.json`](vega_arg_a549_commit_v1.json)** — whether to skip the pilot and commit the full screen directly, against a sequencing-slot deadline. Insufficient.

Start with these two, side by side. The claim map is identical; only `purpose` changes, and the verdict follows it. That is the single point the example exists to make.

## The rest of the set

| Artifact | Role |
|---|---|
| `lyra_pub_myc_adenocarcinoma_v1.json` | The (invented) source study: MYC withdrawal arrests four lung adenocarcinoma lines |
| `lyra_arg_myc_adenocarcinoma_reading_v1.json` | A reading of that study, cited as testimony by both Arguments above |
| `vega_data_lane_traces_v1.json` | Raw western blot lane densities — the calibration ladder and the two samples |
| `vega_model_myc_standard_curve_v1.json` | The standard curve converting band density to relative protein, with its degrees of freedom stated in `modeling_choices` |
| `vega_analysis_myc_densitometry_v1.json` | The Analysis applying the curve to the raw lanes |
| `vega_data_myc_relative_protein_v1.json` | Its output — MYC protein below the assay floor after induction |
| `vega_data_myc_rnaseq_v1.json` | RNA-seq at the same passage, held at an external location rather than embedded — the Ground that cites it is unverifiable by design, and the record says so |

## Reading it

No server needed:

```bash
cd ../../tools && python3 serve.py ../examples/manuscript_example --port 8761
```

**[`../../docs/quickstart.md`](../../docs/quickstart.md)** section 1 covers this in more depth, and section 4 walks through publishing this whole set to a real local server and resetting it afterward — useful for seeing the publish/gate loop work before trusting it with a real community's record.
