# V15 Milestone 5

La M5 introduce un gate topologico: soltanto veri anelli interni chiusi possono essere candidati al riempimento. Le regioni aperte non vengono trasformate in giallo mediante dilatazione o closing morfologico.

## Esito
- closing 0,15 pt: accuracy 92,1481%, F1 giallo 81,400%;
- closing 0,30 pt: accuracy 92,1755%, F1 giallo 81,523%;
- baseline M4: accuracy 92,1843%, F1 giallo 81,564%;
- entrambi gli esperimenti sono stati respinti;
- geometria produttiva M4 conservata;
- 10 test superati;
- due esecuzioni complete identiche.

La M6 dovra ricostruire le superfici aperte mancanti dalla storia delle operazioni vettoriali di paint e clipping, non tramite espansione geometrica.
