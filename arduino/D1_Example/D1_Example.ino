#define LED1 6

void setup() {
  // initialize digital pin LED1 as an output
  pinMode(LED1, OUTPUT);
    
}

void loop() {
 
  digitalWrite(LED1, HIGH);   // turn the LED on (HIGH is the voltage level)
  delay(1000);                // wait for 1000 milliseconds (1000 milliseconds = 1 second)
  
  digitalWrite(LED1, LOW);    // turn the LED off by making the voltage LOW 
  delay(1000);                // wait for 1000 milliseconds

}
