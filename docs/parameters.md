# Parameters File

The parameters file is a JSON dictionary that can control the testbench and vary
the behaviour of testcases, an example of its structure is shown below:

```json linenums="1" title="params.json"
{
    "seed": 1234,
    "verbosity": {
        "tb": "info",
        "tb.int": "debug",
        "tb.test.my_testcase": "warning"
    },
    "profiling": "/path/to/store/profiling.stats",
    "fail_fast": true,
    "testcases": {
        "my_testcase.my_param_a": 123,
        "my_testcase.my_param_b": false
    }
}
```

 * `seed` - sets the random number seeding value for the `tb.random` instance;
 * `verbosity` - control the verbosity of different logging hierarchies:
   * `tb` - sets the global verbosity;
   * `tb.int` - sets the verbosity of Forastero's internal orchestration and
     scheduling methods (i.e. those controlling test setup and teardown);
   * `tb.test.my_testcase` - sets the verbosity for a given testcase;
   * More information can be found in the [logging](./logging.md) documentation.
 * `profiling` - when included this enables [YAPPI](https://pypi.org/project/yappi/)
   profiling of the testbench and writes the profiling data to the given file
   path;
 * `fail_fast` - when set to `true` this will abort the testcase at the first
   scoreboard mismatch, when set to `false` the testcase will be allowed to
   continue to run after a mismatch but will still report the failure;
 * `testcases` - set global or specific testcase parameters, see the details in
   the [testcases](./testcases.md) documentation.

Forastero locates the test parameters file by reading the `TEST_PARAMS`
environment variable:

```bash
$> export TEST_PARAMS=/path/to/params.json
$> make TESTCASE=my_testcase
```
