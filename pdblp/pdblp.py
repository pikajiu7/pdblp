import blpapi
import logging
import datetime
import pandas as pd
from collections import defaultdict
from pandas import DataFrame


class BCon(object):
    def __init__(self, host='localhost', port=8194, debug=False):
        """
        Starting bloomberg API session
        close with session.close()

        Parameters
        ----------
        host: str
            Host name
        port: int
            Port to connect to
        debug: Boolean {True, False}
            Boolean corresponding to whether to log requests messages to stdout
        """
        # Fill SessionOptions
        sessionOptions = blpapi.SessionOptions()
        sessionOptions.setServerHost(host)
        sessionOptions.setServerPort(port)
        # Create a Session
        self.session = blpapi.Session(sessionOptions)
        # initialize logger
        self.debug = debug

    @property
    def debug(self):
        return self._debug

    @debug.setter
    def debug(self, value):
        """
        Set whether logging is True or False
        """
        self._debug = value
        root = logging.getLogger()
        if self._debug:
            # log requests and responses
            root.setLevel(logging.DEBUG)
        else:
            # log only failed connections
            root.setLevel(logging.INFO)

    def start(self):
        """
        start connection and init service for refData
        """
        # Start a Session
        if not self.session.start():
            logging.info("Failed to start session.")
            return
        self.session.nextEvent()
        # Open service to get historical data from
        if not self.session.openService("//blp/refdata"):
            logging.info("Failed to open //blp/refdata")
            return
        self.session.nextEvent()
        # Obtain previously opened service
        self.refDataService = self.session.getService("//blp/refdata")
        self.session.nextEvent()

    def bdh(self, tickers, flds, start_date,
            end_date=datetime.date.today().strftime('%Y%m%d'),
            periodselection='DAILY'):
        """
        Get tickers and fields, return pandas dataframe with column MultiIndex
        of tickers and fields if multiple fields given an Index otherwise.
        If single field is given DataFrame is ordered same as tickers,
        otherwise MultiIndex is sorted

        Parameters
        ----------
        tickers: {list, string}
            String or list of strings corresponding to tickers
        flds: {list, string}
            String or list of strings corresponding to FLDS
        start_date: string
            String in format YYYYmmdd
        end_date: string
            String in format YYYYmmdd
        """
        if type(tickers) is not list:
            tickers = [tickers]
        if type(flds) is not list:
            flds = [flds]
        # Create and fill the request for the historical data
        request = self.refDataService.createRequest("HistoricalDataRequest")
        for t in tickers:
            request.getElement("securities").appendValue(t)
        for f in flds:
            request.getElement("fields").appendValue(f)
        request.set("periodicityAdjustment", "ACTUAL")
        request.set("periodicitySelection", periodselection)
        request.set("startDate", start_date)
        request.set("endDate", end_date)

        logging.debug("Sending Request:\n %s" % request)
        # Send the request
        self.session.sendRequest(request)
        # defaultdict - later convert to pandas
        data = defaultdict(dict)
        # Process received events
        try:
            while(True):
                # We provide timeout to give the chance for Ctrl+C handling:
                ev = self.session.nextEvent(500)
                for msg in ev:
                    logging.debug("Message Received:\n %s" % msg)
                    if (msg.getElement('securityData')
                       .hasElement('securityError')):
                        raise LookupError(msg)
                    ticker = (msg.getElement('securityData')
                              .getElement('security').getValue())
                    fldData = (msg.getElement('securityData')
                               .getElement('fieldData'))
                    for i in range(fldData.numValues()):
                        dt = fldData.getValue(i).getElement(0).getValue()
                        for j in range(1, fldData.getValue(i).numElements()):
                            val = fldData.getValue(i).getElement(j).getValue()
                            data[(ticker, flds[j-1])][dt] = val

                if ev.eventType() == blpapi.Event.RESPONSE:
                    # Response completely received, so we could exit
                    break
        except:
            # flush event queue
            while(self.session.tryNextEvent()):
                pass
            raise

        data = DataFrame(data)
        data.columns.names = ['ticker', 'field']
        data.index = pd.to_datetime(data.index)
        # for single fld drop MultiIndex and return in order tickers appear
        if len(flds) == 1:
            data.columns = data.columns.droplevel(-1)
            data = data.loc[:, tickers]
        return data

    def ref(self, tickers, flds):
        """
        Make a reference data request, get tickers and fields, return pandas
        dataframe with column of tickers and index of flds

        Parameters
        ----------
        tickers: {list, string}
            String or list of strings corresponding to tickers
        flds: {list, string}
            String or list of strings corresponding to FLDS
        """
        if type(tickers) is not list:
            tickers = [tickers]
        if type(flds) is not list:
            flds = [flds]
        # Create and fill the request for the historical data
        request = self.refDataService.createRequest("ReferenceDataRequest")
        for t in tickers:
            request.getElement("securities").appendValue(t)
        for f in flds:
            request.getElement("fields").appendValue(f)

        logging.debug("Sending Request:\n %s" % request)
        # Send the request
        self.session.sendRequest(request)
        data = []
        # Process received events
        try:
            while(True):
                # We provide timeout to give the chance for Ctrl+C handling:
                ev = self.session.nextEvent(500)
                for msg in ev:
                    logging.debug("Message Received:\n %s" % msg)
                    fldData = msg.getElement('securityData')
                    for i in range(fldData.numValues()):
                        ticker = (fldData.getValue(i).getElement("security")
                                  .getValue())
                        reqFldsData = (fldData.getValue(i)
                                       .getElement('fieldData'))
                        for j in range(reqFldsData.numElements()):
                            fld = flds[j]
                            val = reqFldsData.getElement(fld).getValue()
                            data.append((fld, ticker, val))

                if ev.eventType() == blpapi.Event.RESPONSE:
                    # Response completely received, so we could exit
                    break
        except:
            # flush event queue
            while(self.session.tryNextEvent()):
                pass
            raise

        data = DataFrame(data)
        data = data.pivot(0, 1, 2)
        data.index.name = None
        data.columns.name = None
        return data

    def bdib(self, ticker, startDateTime, endDateTime, eventType='TRADE',
             interval=1):
        """
        Get Open, High, Low, Close, Volume, for a ticker.
        Return pandas dataframe

        Parameters
        ----------
        ticker: string
            String corresponding to ticker
        startDateTime: string
            UTC datetime in format YYYY-mm-ddTHH:MM:SS
        endDateTime: string
            UTC datetime in format YYYY-mm-ddTHH:MM:SS
        eventType: string {TRADE, BID, ASK, BID_BEST, ASK_BEST, BEST_BID,
                           BEST_ASK}
            Requested data event type
        interval: int {1... 1440}
            Length of time bars
        """
        # Create and fill the request for the historical data
        request = self.refDataService.createRequest("IntradayBarRequest")
        request.set("security", ticker)
        request.set("eventType", eventType)
        request.set("interval", interval)  # bar interval in minutes
        request.set("startDateTime", startDateTime)
        request.set("endDateTime", endDateTime)

        logging.debug("Sending Request:\n %s" % request)
        # Send the request
        self.session.sendRequest(request)
        # defaultdict - later convert to pandas
        data = defaultdict(dict)
        # Process received events
        flds = ['open', 'high', 'low', 'close', 'volume']
        try:
            while(True):
                # We provide timeout to give the chance for Ctrl+C handling:
                ev = self.session.nextEvent(500)
                for msg in ev:
                    logging.debug("Message Received:\n %s" % msg)
                    barTick = (msg.getElement('barData')
                               .getElement('barTickData'))
                    for i in range(barTick.numValues()):
                        for fld in flds:
                            dt = barTick.getValue(i).getElement(0).getValue()
                            val = (barTick.getValue(i).getElement(fld)
                                   .getValue())
                            data[(fld)][dt] = val

                if ev.eventType() == blpapi.Event.RESPONSE:
                    # Response completly received, so we could exit
                    break
        except:
            # flush event queue
            while(self.session.tryNextEvent()):
                pass
            raise
        data = DataFrame(data)
        data.index = pd.to_datetime(data.index)
        data = data[flds]
        return data

    def custom_req(self, request):
        """
        Utility for sending a predefined request and printing response as well
        as storing messages in a list, useful for testing

        Parameters
        ----------
        request: blpapi.request.Request
            Request to be sent

        Returns
        -------
            List of all messages received
        """
        logging.debug("Sending Request:\n %s" % request)
        self.session.sendRequest(request)
        messages = []
        # Process received events
        try:
            while(True):
                # We provide timeout to give the chance for Ctrl+C handling:
                ev = self.session.nextEvent(500)
                for msg in ev:
                    logging.debug("Message Received:\n %s" % msg)
                    messages.append(msg)
                if ev.eventType() == blpapi.Event.RESPONSE:
                    # Response completely received, so we could exit
                    break
        except:
            # flush event queue
            while(self.session.tryNextEvent()):
                pass
            raise
        return messages

    def stop(self):
        self.session.stop()
