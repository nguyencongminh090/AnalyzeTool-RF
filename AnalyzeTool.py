import subprocess
import psutil
from queue import Queue, Empty
from threading import Thread


def removesuffix(string, symbol):
    return string.split(symbol)[0]


def removeprefix(string, symbol):
    return string.split(symbol)[1]


def coordStr2Num(coord: str):
    '''
    Example:
        Input: '7,7'
        Output: 'h8'
    -> Return String Coord From Number Coord 
    NOTE: (0,0) is bottom-left
    '''
    # return f'{ord(coord[0]) - 97},{15 - int(coord[1:])}'
    return f'{ord(coord[0]) - 97},{int(coord[1:]) - 1}'


def coordNum2Str(coord: str):
    '''
    Return Number Coord From String Coord
    '''
    coord = coord.split(',')
    return f'{chr(int(coord[0]) + 97)}{int(coord[1]) + 1}'


class NonBlockingStreamReader:
    def __init__(self, stream):
        self.__stream = stream
        self.__queue = Queue()

        def populateQueue(_stream, queue):
            while True:
                line = _stream.readline()
                if line:
                    queue.put(line)
                # else:
                #     raise UnexpectedEndOfStream

        self.__thread = Thread(target=populateQueue, args=(self.__stream, self.__queue))
        self.__thread.daemon = True
        self.__thread.start()

    def readline(self):
        try:
            return self.__queue.get(block=True, timeout=0.1)
        except Empty:
            return None

  
class Engine:
    def __init__(self, path):
        '''
        Connect to engine
        path=<engine's path>
        '''
        self.__path = path
        self.__engineName = self.__path.split('\\')[-1]
        self.__engine = subprocess.Popen(self.__path, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE,
                                         bufsize=1, universal_newlines=True)
        self.__nbsr = NonBlockingStreamReader(self.__engine.stdout)
        self.info_dict = {
            'timeout_match': 60000,
            'timeout_turn': 60000,
            'game_type': 1,
            'rule': 1,
            'time_left': 60000,
            'max_memory': 0,
            }
        self.__engineInfo = {'name': ...,
                             'version': ...,
                             'author': ...,
                             'email': ...,
                             'ponder': False}

        self.__lockMessage = False
        self.__lastMessage = ''
        
        # Correct input
        dictionary = ('stop', 'display', 'get link', 'best move', 'analyze',
                      'play by time', 'manual', 'auto', 'quit', 'swap2')
        self.__autoCorrect = AutoCorrect(dictionary)

    def kill(self):
        self.__engine.kill()

    def send(self, *command):
        '''
        Send command to engine via stdin
        '''
        new_command = []
        for i in range(len(command)):
            if i == 0:
                new_command.append(str(command[i]).upper())
            else:
                new_command.append(str(command[i]))
        command = ' '.join(new_command)
        self.__engine.stdin.write(command + '\n')
        # DEBUG
        # print('<-o-', command)

    def receive(self):
        text = self.__nbsr.readline()
        return removesuffix(text, '\n') if text is not None else None

    def getMove(self):
        flag = False
        output = ...
        while True:
            text = self.receive()
            if text is not None and 'MESSAGE' not in text:
                flag = True
                output = text
                print('-x->', text)
            elif text is not None:
                print('-o->', ' '.join(text.split()[1:]).upper())
            elif flag and text is None:
                return coordNum2Str(output)
                
    def getMessage(self):
        flag = False
        message = []
        while True:
            text = self.receive()
            if text is not None:
                message.append(text)
                flag = True
            elif text is None and flag:
                return message

    def readMessage(self):        
        flag = False
        text = ''
        while self.__lockMessage:
            text = self.receive()
            if text is not None and 'MESSAGE' not in text:
                flag = True
                print('-x->', coordNum2Str(text))
                self.__lastMessage = text
                self.__lockMessage = False
            elif text is not None:
                message = ' '.join(text.split()[1:])
                print('-o->', preprocessMessage(message))    
                self.__lastMessage = ' '.join(text.split()[1:]).upper()         
            elif text is None and flag:
                return
        if not flag:
            self.__lockMessage = True
            return self.readMessage()

    def isReady(self, board_size=15):
        self.send('start', board_size)
        while True:
            flag = False
            line = self.__nbsr.readline()
            if line is not None and line.strip().upper() == 'OK':
                return True
            if line is not None:
                flag = True
            if line is None and flag:
                return False

    def setInfo(self, info=dict()):
        '''
        Input: Dict
        '''
        # Enable Ponder
        if self.__engineInfo['ponder']:
            info['pondering'] = 1
        self.info_dict.update(info)
        for i in self.info_dict:
            self.send('INFO', i, self.info_dict[i])
            
    def setTime(self, seconds):
        '''
        Set time unlimited: -1
        Set time by seconds: x
        '''
        if seconds != -1 and seconds > 0:
            seconds = abs(seconds * 1000)
        self.setInfo({'timeout_match': seconds,
                        'timeout_turn': seconds
                     })
        print(f'-> Time set to {seconds}s')        

    def __play(self, position: list):        
        position = position.strip().split()
        for i in range(len(position)):
            position[i] = coordStr2Num(position[i])

        self.send('board')
        for i in range(len(position)):
            if len(position) % 2 == i % 2:
                self.send(position[i] + ',' + '1')
            else:
                self.send(position[i] + ',' + '2')
        self.send('done')
        
    def __makeSwap2(self, position: list):        
        position = position.strip().split()
        for i in range(len(position)):
            position[i] = coordStr2Num(position[i])

        self.send('yxboard')
        for i in range(len(position)):
            if len(position) % 2 == i % 2:
                self.send(position[i] + ',' + '1')
            else:
                self.send(position[i] + ',' + '2')
        self.send('done')
        self.send('yxbalancetwo 0')

    def analyze(self, position: list, mode='auto'):
        '''
        Example:
            Input: h8 h9 h10
            Ouput: <best move>
            
            mode: [auto, manual (for analysis)]
        '''
        def _stop():
            self.send('stop')
            self.__lockMessage = False
            self.__lastMessage = ''
            thread.join()
            
        def _getLink():
            pv = self.__lastMessage.split('PV')[1].strip().lower().split()
            pv = position.split() + pv
            lenPV = len(pv) - 1
            pv = ''.join(pv)
            print(f'https://www.playok.com/p/?g=gm+{pv}#{lenPV}')
            
        def _display():
            try:
                n = int(command[8:-1]) if len(command) > 7 else None
                pv = self.__lastMessage.split('PV')[1].strip().lower().split()                    
                pv = position.split() + pv[:n if n is not None and n < len(pv) else None]
                board = Board(15)
                board.setPos(pv)
                board.printBoard()
            except:
                print('An error occurred!')
            
        getInput = self.__autoCorrect.search(input('(Swap2/Best move): ').strip().lower())
        if getInput == 'swap2':
            print('==Make Swap2==')
            self.__makeSwap2(position)
        else:
            print('==Best Move==')
            self.__play(position)
        
        if mode == 'auto':
            self.getMove()
        else:
            self.__lockMessage = True    # Unlock
            thread = Thread(target=self.readMessage)
            thread.start()
            while self.__lockMessage:
                command = input('Command: ').strip().lower()
                if self.__autoCorrect.search(command, len(command)) == 'stop':
                    _stop()
                    break
                elif self.__autoCorrect.search(command, len(command)) == 'get link':
                    _getLink()
                elif self.__autoCorrect.search(command, len(command)) == 'display':
                    _display()

    def about(self):
        self.send('ABOUT')
        info = self.getMessage()[-1].split(', ')
        stack = []
        variable = ('name', 'version', 'author', 'email')
        for i in info:
            if '=' in i:
                data: list[str] = i.split('=')
                data[1] = removeprefix(data[1], '"')
                data[1] = removesuffix(data[1], '"')
                stack.append(data[0])
                stack.append(data[1])
            else:
                data = removesuffix(i, '"')
                stack[-1] += f', {data}'
        for var in variable:
            if var in stack:
                self.__engineInfo[var] = stack[stack.index(var) + 1]
        if self.__engineInfo['name'].upper() == 'RAPFI':
            self.__engineInfo['ponder'] = True

    def getInfo(self):
        return self.__engineInfo
    
    def control(self):
        '''
        Analyze
        Play by time
        Swap2
        '''
        while True:
            getInput = input('Input:').strip().lower()
            if self.__autoCorrect.search(getInput) == 'analyze':
                print('-> Not include space!')
                getPos = Coord.genString(*Coord().getString(input('Position: ').strip().lower(), 15))
                if not getPos:
                    print('--> Not Valid!')
                    continue
                else:
                    print('-> Pos:', getPos)
                print('-> Time set by seconds.')
                getTime = int(input('Time: '))
                self.setTime(getTime)
                getType = self.__autoCorrect.search(input('-> (Manual/Auto)').strip().lower())                
                if not getType:
                    print('--> Not Valid!')
                    continue
                else:
                    if getTime == -1:
                        getType = 'manual'
                    print('-> Type:', getType)
                self.analyze(getPos, getType)
            elif self.__autoCorrect.search(getInput) == 'quit':
                break


def round(number, places=0):
    place = 10 ** places
    rounded = (int(number*place + 0.5 if number >= 0 else -0.5)) / place
    if rounded == int(rounded):
        rounded = int(rounded)
    return rounded


def calcWinrate(x):
    '''
    Return Winrate from CP scores
    '''
    e = 2.718281828459045235360287471352662497757247093699959574966
    x /= 200
    return round((e**x)/(e**x + 1) * 100)


def preprocessMessage(message):
    '''
    Collapse message + winrate-percent
    '''
    # Process the 'eval' value
    message = message.lower()
    ev = ''
    pv = ''
    prefix = ''
    if 'ev' in message:
        ev = message.split()[message.split().index('ev') + 1]
        if 'm' in ev[:2]:
            ev = (100 + int(ev[:2].replace('m', '100'))) // 2
        else:
            ev = calcWinrate(int(ev))
    if 'pv' in message:
        pv = ' '.join(message.split()[message.split().index('pv') + 1:][:10]) + \
                     (' ...' if len(message.split()[message.split().index('pv') + 1:]) > 10 else '')
        prefix = ' '.join(message.split()[:message.split().index('pv') + 1])
        
    message = f"{prefix} {pv} (Winrate: {ev}%)"
    return message.upper()
        

class Coord:
    @staticmethod
    def validString(n, *arg):
        '''
        param n: Length of Board
        '''
        for coord in arg:
            try:
                if ord(coord[0]) - 96 < 0  or ord(coord[0]) - 96 > n or\
                   int(coord[1:]) < 0 or int(coord[1:]) > n:
                    return False
            except:
                return False
        return True
    
    def getString(self, string, n):
        while string:
            if not self.validString(n, string[:2]):
                string = string[1:]
            else:
                string = self.formatString(string)
                break
        it = 0
        while it < len(string):
            if not self.validString(n, string[it]):
                string.remove(string[it])
            else:
                it += 1
        return string
            
    @staticmethod
    def formatString(string):
        listMove = []
        while string:
            cur = string[0]
            string = string[1:]
            while len(string) > 0 and string[0].isnumeric():
                cur += string[0]
                string = string[1:]
            listMove.append(cur)
        return listMove
    
    @staticmethod
    def genString(*arg):
        return ' '.join(arg)
    
    @staticmethod
    def coordStr2Num(coord: str):
        '''
        Example:
            Input: '7,7'
            Output: 'h8'
        -> Return String Coord From Number Coord 
        NOTE: (0,0) is bottom-left
        '''
        # return f'{ord(coord[0]) - 97},{15 - int(coord[1:])}'
        return f'{ord(coord[0]) - 97},{int(coord[1:]) - 1}'

    @staticmethod
    def coordNum2Str(coord: str):
        '''
        Return Number Coord From String Coord
        '''
        coord = coord.split(',')
        return f'{chr(int(coord[0]) + 97)}{int(coord[1]) + 1}'


class Board:
    def __init__(self, n, distance=3):
        '''
        param n: Length
        '''
        self.__n = n
        self.__distance = distance
        self.__createBoard()

    def __createBoard(self):
        self.__board = [['.'.center(self.__distance) for _ in range(self.__n+1)] for _ in range(self.__n+1)]
        
        for i in range(self.__n):
            self.__board[-1][i] = chr(65+i).center(self.__distance)

        for i in range(self.__n):
            self.__board[i][-1] = str(15-i).rjust(self.__distance)
            
        self.__board[7][7] = '*'.center(self.__distance)
            
        self.__board[-1][-1] = ''

    def setMove(self, pos:tuple, color):
        '''
        param color:
        1: X (black)
        2: O (white)
        '''
        if color == 1:        
            self.__board[self.__n-1-pos[1]][pos[0]] = '●'.center(self.__distance)
        else:
            self.__board[self.__n-1-pos[1]][pos[0]] = '○'.center(self.__distance)
            
    def setPos(self, arg:list):
        for i in range(len(arg)):
            arg[i] = (int(Coord.coordStr2Num(arg[i]).split(',')[0]), int(Coord.coordStr2Num(arg[i]).split(',')[1]))
            if i % 2 == 0:
                self.setMove(arg[i], 1)
            else:
                self.setMove(arg[i], 2)
                
    def takeBackPos(self, pos:tuple):
        self.__board[n-1-pos[1]][n-1-pos[0]] = '.'.center(self.__distance)

    def resetBoard(self):
        self.__createBoard()
    
    def printBoard(self):
        board = self.__board[::]
        for line in range(len(board)):
            board[line] = ''.join(board[line])
            print(board[line])           

    def getBoard(self):
        board = self.__board[::]
        for line in range(len(board)):
            board[line] = ''.join(board[line])
        return '\n'.join(board)

    def __repr__(self):
        return self.getBoard()

    def __str__(self):
        return self.getBoard()
    
    
class TrieNode:
    def __init__(self):
        self.word = None
        self.children = {}

    def insert( self, word ):
        node = self
        for letter in word:
            if letter not in node.children: 
                node.children[letter] = TrieNode()
            node = node.children[letter]
        node.word = word
    
    
class AutoCorrect:
    def __init__(self, dictionary:tuple):
        assert len(dictionary) > 0
        self.__dictionary = dictionary
        self.__trieTree = TrieNode()
        self.__genTree()

    def __genTree(self):
        for word in self.__dictionary:
            self.__trieTree.insert(word)
            
    @staticmethod
    def __maxMatch(string, string1):
        array = [[0 for _ in range(len(string1))] for _ in range(len(string))]
        maxLength = 0
        for i in range(0, len(string)):
            for j in range(len(string1)):
                if string[i] == string1[j]:
                    array[i][j] = 1
                    if array[i-1][j-1] >= 1 and i > 0 and j > 0:
                        array[i][j] = array[i-1][j-1] + 1
            if max(array[i]) > maxLength:
                maxLength = max(array[i])
        return abs(len(string) - maxLength)
            

    def search(self, word, maxCost=4):
        currentRow = list(range(len(word) + 1))
        results = []    
        for letter in self.__trieTree.children:
            self.__searchRecursive(self.__trieTree.children[letter], letter, word, currentRow, results, maxCost)
        if results:
            return min(results)[-1]
        return ''

    def __searchRecursive(self, node, letter, word, previousRow, results, maxCost):
        columns = len(word ) + 1
        currentRow = [previousRow[0] + 1]
        for column in range(1, columns):
            insertCost = currentRow[column - 1] + 1
            deleteCost = previousRow[column] + 1

            if word[column - 1] != letter:
                replaceCost = previousRow[ column - 1 ] + 1
            else:                
                replaceCost = previousRow[ column - 1 ]

            currentRow.append(min(insertCost, deleteCost, replaceCost))
            
        if currentRow[-1] <= maxCost and node.word != None:
            results.append((currentRow[-1] + self.__maxMatch(word, node.word), node.word))
            
        if min(currentRow) <= maxCost:
            for letter in node.children:
                self.__searchRecursive(node.children[letter], letter, word, currentRow, results, maxCost)


def main():
    engine = Engine('./pbrain-rapfi_avx2')
    engine.about()
    engine.getInfo()
    engine.isReady()
    engine.control()


if __name__ == '__main__':
    main()
