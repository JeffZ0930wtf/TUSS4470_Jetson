set pagination off
target sim
load
break usac_test_complete
run
printf "USAC_TEST_RESULT=%d\n", g_usac_test_result
quit
