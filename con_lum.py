import nidaqmx
import logging

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Replace with your actual device/port/line
DAQ_CHANNEL = "cDAQ1Mod1/port0/line3"
#DAQ_CHANNEL = "cDAQ1Mod1/port0/line0"
def control_led():
    """
    Continuously prompt the user for input:
      - "1" => Turn LED (digital output) ON
      - "0" => Turn LED OFF
      - "2" => Attempt to read the current state of the line (if hardware allows)
      - "q" => Quit
    """
    with nidaqmx.Task() as task:
        # Configure the DO channel. If you need to read from a separate DI channel,
        # you would create another Task or channel for DI here.
        task.do_channels.add_do_chan(DAQ_CHANNEL)
        logging.info(f"Configured digital output channel: {DAQ_CHANNEL}")

        while True:
            user_input = input("Enter 2->read, 1->ON, 0->OFF, q->quit: ").lower()

            if user_input == "q":
                logging.info("Exiting the program.")
                break

            elif user_input == "2":
                # Attempt to read the state (may fail or return stale data if hardware doesn't support DO readback)
                try:
                    state = task.read()
                    logging.info(f"Current channel state: {state}")
                except Exception as e:
                    logging.warning(f"Could not read DO line state: {e}")

            elif user_input == "1":
                logging.info("Turning LED ON.")
                task.write(True)

            elif user_input == "0":
                logging.info("Turning LED OFF.")
                task.write(False)

            else:
                logging.warning(f"Invalid input: '{user_input}'. Please enter 2, 1, 0, or q.")

if __name__ == "__main__":
    control_led()

