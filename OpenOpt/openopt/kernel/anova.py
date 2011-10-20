
#from FDmisc import FuncDesignerException
#from __init__ import __version__ as fdversion
from numpy import inf, copy, abs, all, floor, log10, asfarray, asscalar

TkinterIsInstalled = True
try:
    from Tkinter import Tk, Toplevel, Button, Entry, Menubutton, Label, Frame, StringVar, DISABLED, ACTIVE, END, IntVar, \
    Radiobutton, Canvas
    from tkFileDialog import asksaveasfilename, askopenfile
except ImportError:
    TkinterIsInstalled = False

xtolScaleFactor = 1e-5

class MFA:
    filename = None # Python pickle file where to save results
    
    def startSession(self):
        assert TkinterIsInstalled, '''
        Tkinter is not installed. 
        If you have Linux you could try using 
        "apt-get install python-tk"'''
        import os
        hd = os.getenv("HOME")
        self.hd = hd
        root = Tk()
        self.root = root
        root.wm_title(' OpenOpt multifactor analysis tool for experiment planning ')
        SessionSelectFrame = Frame(root)
        SessionSelectFrame.pack(side='top', padx=230, ipadx = 40, fill='x', expand=True)
        var = StringVar()
        var.set('asdf')
        Radiobutton(SessionSelectFrame, variable = var, text = 'New', indicatoron=0, \
                    command=lambda: (SessionSelectFrame.destroy(), self.create())).pack(side = 'top', fill='x', pady=5)
        Radiobutton(SessionSelectFrame, variable = var, text = 'Load', indicatoron=0,  \
                    command=lambda:self.load(SessionSelectFrame)).pack(side = 'top', fill='x', pady=5)
        root.mainloop()
    
    def load(self, SessionSelectFrame):
        file = askopenfile(defaultextension='.pck', initialdir = self.hd, filetypes = [('Python pickle files', '.pck')])
        if file in (None, ''):
            return
        SessionSelectFrame.destroy()
    
    def create(self, n_=[], lb_=[], ub_=[], tol_=[], val_=[], cp_={}):
        root = self.root
        self.NameEntriesList, self.LB_EntriesList, self.UB_EntriesList, self.TolEntriesList, self.ValueEntriesList = n_, lb_, ub_, tol_, val_
        self.calculated_points = cp_

        # Title
        #root.wm_title(' FuncDesigner ' + fdversion + ' Manager')
        
        C = Canvas(root)
        
        """                                              Buttons                                               """
        Frame(root).pack(ipady=4)
        #Label(root, text=' FuncDesigner ' + fdversion + ' ').pack()


        #                                                   Upper Frame
        UpperFrame = Frame(root)
        UpperFrame.pack(side = 'top', expand=False, fill = 'x')
        
        GoalSelectFrame = Frame(UpperFrame, relief = 'ridge', bd=2)
        GoalSelectText = StringVar(value = 'Goal:')
        Label(GoalSelectFrame, textvariable = GoalSelectText).pack(side = 'left')
        goal = StringVar()
        r1 = Radiobutton(GoalSelectFrame, text = 'Minimum', value = 'min', variable=goal)
        r1.pack(side = 'left')
        r2 = Radiobutton(GoalSelectFrame, text = 'Maximum', value = 'max', variable=goal)
        r2.pack(side = 'left')
        goal.set('min')    
        GoalSelectFrame.pack(side = 'left', padx = 10)
        self.goal = goal
        
        ObjectiveToleranceFrame = Frame(UpperFrame, relief = 'ridge', bd=2)
        ObjectiveToleranceFrame.pack(side='left')
        Label(ObjectiveToleranceFrame, text='Objective function tolerance:').pack(side = 'left')
        ObTolEntry = Entry(ObjectiveToleranceFrame)
        ObTolEntry.pack(side='left')
        self.ObTolEntry = ObTolEntry
            
        #                                                   Variables Frame
        varsRoot = Frame(root)
       
       
        #                                                    Lower frame
        LowerFrame = Frame(varsRoot)
        LowerFrame.pack(side = 'bottom', expand=True, fill = 'x')

        SaveButton = Button(LowerFrame, text = 'Save', command = self.save)
        SaveButton.pack(side='left', padx = 15)
        SaveAsButton = Button(LowerFrame, text = 'Save As ...', command = self.save)
        SaveAsButton.pack(side='left')
    #    PlotButton = Button(LowerFrame, text = 'Plot', command = lambda: Plot(C, self.prob))
    #    PlotButton.pack(side='left')
     
        ObjValNum = IntVar()
        ObjValNum.set(1)
       
        ObjVal = StringVar()
        ObjEntry = Entry(LowerFrame, textvariable = ObjVal)

        NN = StringVar(LowerFrame)
        NN_Label = Label(LowerFrame, textvariable = NN)
        
        
        names, lbs, ubs, tols, currValues = \
        Frame(varsRoot), Frame(varsRoot), Frame(varsRoot), Frame(varsRoot), Frame(varsRoot)
        Label(names, text=' Variable Name ').pack(side = 'top')
        Label(lbs, text=' Lower Bound ').pack(side = 'top')
        Label(ubs, text=' Upper Bound ').pack(side = 'top')
        Label(tols, text=' Tolerance ').pack(side = 'top')
        
        ValsColumnName = StringVar()
        ValsColumnName.set(' Initial Point ')
        Label(currValues, textvariable=ValsColumnName).pack(side = 'top')
        
        
        #                                                    Commands Frame
        CommandsRoot = Frame(root)
        CommandsRoot.pack(side = 'right', expand = False, fill='y')
        
       
        AddVar = Button(CommandsRoot, text = 'Add Variable', command = \
                        lambda: self.addVar(names, lbs, ubs, tols, currValues))
        AddVar.pack(side = 'top', fill='x')

        Next = Button(CommandsRoot, text = 'Next', command = lambda: ObjValNum.set(ObjValNum.get()+1))
        #Next.pack(side='bottom',  fill='x')

        names.pack(side = 'left', ipady=5)
        lbs.pack(side = 'left', ipady=5)
        ubs.pack(side = 'left', ipady=5)
        tols.pack(side = 'left', ipady=5)
        currValues.pack(side = 'left', ipady=5)
        #currValues.pack_forget()
        
        varsRoot.pack()
        
        Start = Button(CommandsRoot, text = 'Start', \
                       command = lambda: (Start.destroy(), \
                                          Next.pack(side='bottom',  fill='x'), 
                                          #C.pack(side = 'bottom', expand=True, fill='both'), 
                                          r1.config(state=DISABLED), 
                                          r2.config(state=DISABLED), 
                                          ObTolEntry.config(state=DISABLED), 
                                          ObjEntry.pack(side='right', ipady=4),
                                          NN_Label.pack(side='right'), \
                                          self.startOptimization(root, varsRoot, AddVar, currValues, ValsColumnName, ObjEntry, ObjValNum, Next, NN, 
                                                            goal.get(), float(ObTolEntry.get()), C)))
        Start.pack(side = 'bottom', fill='x')
        
        if len(n_):
            pass
        else:
            self.addVar(names, lbs, ubs, tols, currValues)
#        for i in range(nVars):
#            self.addVar(names, lbs, ubs, tols, currValues)
        
        

    def addVar(self, names, lbs, ubs, tols, currValues):
        nameEntry, lb, ub, tol, valEntry = Entry(names), Entry(lbs), Entry(ubs), Entry(tols), Entry(currValues)
        self.NameEntriesList.append(nameEntry)
        self.LB_EntriesList.append(lb)
        self.UB_EntriesList.append(ub)
        self.TolEntriesList.append(tol)
        self.ValueEntriesList.append(valEntry)
        nameEntry.pack(side = 'top')
        lb.pack(side = 'top')
        ub.pack(side = 'top')
        tol.pack(side = 'top')
        valEntry.pack(side = 'top')
        
    def save_as(self, filename=None):
        if filename is None:
            filename = asksaveasfilename(defaultextension='.pck', initialdir = self.hd, filetypes = [('Python pickle files', '.pck')])
        if filename in (None, ''):
            return
        self.filename = filename
        names = [s.get() for s in self.NameEntriesList]
        lbs = [s.get() for s in self.LB_EntriesList]
        ubs = [s.get() for s in self.UB_EntriesList]
        tols = [s.get() for s in self.TolEntriesList]
        values = [s.get() for s in self.ValueEntriesList]
        goal = self.goal.get()
        ObjTol = self.ObTolEntry.get()
        calculated_points = self.calculated_points
        S = {'names':names, 'lbs':lbs, 'ubs':ubs, 'tols':tols, 'values':values, 'goal':goal, \
        'ObjTol':ObjTol, 'calculated_points':calculated_points}
        
        # TODO: handle exceptions
        file = open(filename, "w")
        import pickle
        pickle.dump(S, file)
        file.close()
        
    save = lambda self: self.save_as(self.filename)

    def startOptimization(self, root, varsRoot, AddVar, currValues, \
                          ValsColumnName, ObjEntry, ObjValNum, Next, NN, goal, objtol, C):
        AddVar.destroy()
        ValsColumnName.set('Experiment parameters')
        n = len(self.NameEntriesList)
        Names, Lb, Ub, Tol, x0 = [], [], [], [], []
        for i in range(n):
            N, L, U, T, valEntry = \
            self.NameEntriesList[i], self.LB_EntriesList[i], self.UB_EntriesList[i], self.TolEntriesList[i], self.ValueEntriesList[i]
            N.config(state=DISABLED)
            L.config(state=DISABLED)
            U.config(state=DISABLED)
            T.config(state=DISABLED)
            #valEntry.config(state=DISABLED)
            name, lb, ub, tol, val = N.get(), L.get(), U.get(), T.get(), valEntry.get()
            Names.append(name)
            x0.append(float(val))
            Lb.append(float(lb) if lb != '' else -inf)
            Ub.append(float(ub) if ub != '' else inf)
            
            # TODO: fix zero
            Tol.append(float(tol) if tol != '' else 0) 
            
        x0, Tol, Lb, Ub = asfarray(x0), asfarray(Tol), asfarray(Lb), asfarray(Ub)
        x0 *= xtolScaleFactor / Tol
        from openopt import NLP
        p = NLP(objective, x0, lb = Lb * xtolScaleFactor / Tol, ub=Ub * xtolScaleFactor / Tol)
        self.prob = p
        #calculated_points = [(copy(x0), copy(float(ObjEntry.get())))
        p.args = (Tol, self, ObjEntry, p, root, ObjValNum, Next, NN, objtol, C)
        #p.graphics.rate = -inf
        #p.f_iter = 2
        p.solve('bobyqa', iprint = -1, goal = goal)#, plot=1, xlabel='nf')
        Next.config(state=DISABLED)
        #print('Finished')

    def Plot(C, p):
        pass
        #C.create_polygon()
    #    import os
    #    if os.fork():
    #        import pylab
    #        pylab.plot(p.iterValues.f)
    #        pylab.show()

def objective(x, Tol, mfa, ObjEntry, p, root, ObjValNum, Next, NN, objtol, C):
    Key = ''
    Values = []
    ValueEntriesList = mfa.ValueEntriesList
    calculated_points = mfa.calculated_points
    for i in range(x.size):
        Format = '%0.9f' if Tol[i] == 0 else ('%0.' + ('%d' % (-floor(log10(Tol[i])))) + 'f') if Tol[i]<1 else '%d'
        tmp = x[i] * Tol[i] / xtolScaleFactor
        key = Format % tmp
        Key += key + ' '
        Values.append(key)

    if Key in calculated_points:
        return calculated_points[Key]
   
    for i in range(x.size):
        ValueEntriesList[i].delete(0, END)
        ValueEntriesList[i].insert(0, Values[i])
        
    NN.set('Enter experiment %i result:' % int(ObjValNum.get()))
    
    ObjEntry.delete(0, END)
    root.wait_variable(ObjValNum)
    r = float(ObjEntry.get()) 
    
#    from scipy import rand
#    r = abs(x[0]* Tol[0] / xtolScaleFactor-0.13) + abs(x[1]* Tol[1] /xtolScaleFactor-0.15) #+ 0.0001 * rand(1)

    r *= 1e-4 / objtol
    calculated_points[Key] = asscalar(copy(r)) # for more safety
    
#    rr = []
#    for i, val in enumerate(p.iterValues.f):
#        rr.append(i)
#        rr.append(val)
#    rr.append(i+1)
#    rr.append(r)
#    if len(p.iterValues.f) > 1:
#        C.create_line(*rr, fill = 'blue')
    return r
    

if __name__ == '__main__':
    MFA().startSession()
    